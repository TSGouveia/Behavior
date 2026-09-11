// ============================================================
// Drosophila larva tracking via median background subtraction
// ============================================================
// What it does:
//   0. Asks you to select the FOLDER containing your PNG image
//      sequence for one video, and opens it as a virtual stack
//   1. Lets you pick which color channel gives the best larva contrast
//   2. Lets you draw/confirm a circular ROI over the arena
//   3. Lets you outline one larva once to auto-calibrate expected size
//   4. Calibrates px -> mm using a distance you measure on the ruler
//   5. Builds a static background from a SAMPLE of frames (median)
//   6. Determines one fixed threshold from a representative frame
//   7. Loops frame-by-frame: subtract background, threshold, find
//      the largest particle, log its coordinates, then discard the
//      frame before moving on
//   8. Saves a CSV with per-frame coordinates
//
// EXPECTED INPUT: a folder containing one PNG per frame (e.g. from
// ffmpeg: frame_00001.png, frame_00002.png, ...), all belonging to
// a single recording.
//
// MEMORY DESIGN: this macro NEVER loads the whole video into RAM.
// The image sequence is opened as a virtual stack, and every
// processing step below works on a single frame at a time, closing
// it before moving to the next. This means it works the same way
// whether your video is 10 seconds or 30 minutes long, without
// needing to raise Fiji's memory allocation.
// ============================================================

// ---- USER SETTINGS (edit these) ----
gaussSigma   = 2.0; // smoothing before threshold, reduces banding/noise
                     // (raise this further, e.g. 3-4, if the interactive
                     // threshold check in Step 6 still looks noisy)
fps          = 30;  // frames per second of your recording
outputPath   = "";  // leave blank to be prompted for save location
bgSampleSize = 300; // number of frames sampled to build the background
                     // (more = more accurate background, slower to build;
                     // 300 is plenty for a background that doesn't change)

// ---- Helper: extract one frame, in the chosen channel, as a small ----
// ---- standalone 8-bit image. This is the core memory-saving trick: ----
// ---- it only ever creates ONE small image, never a full-stack copy. ----
function getChannelFrame(srcTitle, sliceIndex, isRGBFlag, channelName) {
    selectWindow(srcTitle);
    setSlice(sliceIndex);
    run("Duplicate...", "duplicate range=" + sliceIndex + "-" + sliceIndex);
    dupTitle = getTitle();
    if (!isRGBFlag) {
        if (bitDepth() != 8) run("8-bit");
        return dupTitle;
    }
    run("Split Channels");
    if (channelName == "Red") {
        keep = dupTitle + " (red)";
        d1 = dupTitle + " (green)"; d2 = dupTitle + " (blue)";
    } else if (channelName == "Green") {
        keep = dupTitle + " (green)";
        d1 = dupTitle + " (red)"; d2 = dupTitle + " (blue)";
    } else {
        keep = dupTitle + " (blue)";
        d1 = dupTitle + " (red)"; d2 = dupTitle + " (green)";
    }
    close(d1);
    close(d2);
    return keep;
}

// ---- Step 0: Select folder and open the PNG image sequence ----
inputDir = getDirectory("Select the folder containing the PNG image sequence for this video");
list = getFileList(inputDir);

nImgFiles = 0;
for (i = 0; i < list.length; i++) {
    if (endsWith(toLowerCase(list[i]), ".png")) nImgFiles++;
}

if (nImgFiles == 0) {
    exit("No .png files found in the selected folder:\n" + inputDir +
         "\n\nConvert your video to a PNG sequence first (ffmpeg), then re-run.");
}

run("Image Sequence...", "open=[" + inputDir + "] sort use");

if (nImages == 0) {
    exit("Nothing was opened. Re-run the macro and select a folder\ncontaining a PNG image sequence.");
}

// ---- Prep ----
origTitle = getTitle();
getDimensions(w, h, ch, sl, fr);
numSlices = nSlices();
isRGB = (bitDepth() == 24);

// ---- Step 1: Channel selection (preview on ONE frame only) ----
chosenChannel = "Red"; // default/placeholder if grayscale
if (isRGB) {
    selectWindow(origTitle);
    setSlice(1);
    run("Duplicate...", "duplicate range=1-1");
    previewTitle = getTitle();
    run("Split Channels");
    Dialog.create("Pick best channel");
    Dialog.addMessage("Compare the Red/Green/Blue windows now open.\nPick whichever shows the larva with the most contrast\nagainst the background.");
    Dialog.addChoice("Channel to use:", newArray("Red", "Green", "Blue"), "Red");
    Dialog.show();
    chosenChannel = Dialog.getChoice();
    close(previewTitle + " (red)");
    close(previewTitle + " (green)");
    close(previewTitle + " (blue)");
}

// ---- Step 2: Arena ROI (drawn on the original frame 1) ----
selectWindow(origTitle);
setSlice(1);
run("Select None");
waitForUser("Arena ROI", "Draw an oval/circle selection tightly around the INSIDE\nedge of the petri dish, then click OK.");
roiManager("Reset");
roiManager("Add");

// ---- Step 3: Larval size calibration (also on frame 1) ----
setTool("freehand");
waitForUser("Measure larval size", "Outline one larva with the freehand tool\n(doesn't need to be perfect - just representative),\nthen click OK.");
run("Set Measurements...", "area redirect=None decimal=2");
run("Measure");
larvalSize = getResult("Area", nResults - 1);
run("Clear Results");
run("Select None");

minSize = 0.35 * larvalSize;
maxSize = 1.50 * larvalSize;
print("Measured larval size: " + larvalSize + " px^2  ->  using range " + minSize + "-" + maxSize + " px^2");

// ---- Step 4: Pixel-to-mm calibration (also on frame 1) ----
knownMM = getNumber("Known real-world distance you are about to draw (mm):", 10);
waitForUser("Calibration", "Draw a straight line over exactly " + knownMM + " mm on the ruler\n(on the current image), then click OK.");
run("Set Scale...", "distance=0 known=" + knownMM + " unit=mm");
getVoxelSize(pxWidth, pxHeight, pxDepth, unit);
if (pxWidth == 1) {
    pxPerMM = getNumber("Could not read a line ROI. Enter pixels-per-mm manually:", 10.7);
    pxWidth = 1/pxPerMM;
    pxHeight = 1/pxPerMM;
}
run("Select None");

// Get Arena ROI bounds and calculate center & radius
roiManager("Select", 0);
Roi.getBounds(arenaX, arenaY, arenaW, arenaH);
arenaCenterXPx = arenaX + arenaW / 2.0;
arenaCenterYPx = arenaY + arenaH / 2.0;
arenaRadiusPx = (arenaW + arenaH) / 4.0;
arenaCenterXMm = arenaCenterXPx * pxWidth;
arenaCenterYMm = arenaCenterYPx * pxHeight;
arenaRadiusMm = arenaRadiusPx * ((pxWidth + pxHeight) / 2.0);
run("Select None");
print("Arena center: (" + arenaCenterXPx + ", " + arenaCenterYPx + ") px [" + arenaCenterXMm + ", " + arenaCenterYMm + " mm], radius: " + arenaRadiusPx + " px [" + arenaRadiusMm + " mm]");

// ---- Step 5: Build background from a SAMPLE of frames (not all of them) ----
// PERFORMANCE: batch mode hides all images and suppresses GUI redraws,
// typically giving a 10-50x speedup for frame-by-frame processing.
setBatchMode(true);
print("Building background from a sample of frames...");
step = floor(numSlices / bgSampleSize);
if (step < 1) step = 1;

sampleTitles = newArray(0);
idx = 1;
while (idx <= numSlices) {
    ft = getChannelFrame(origTitle, idx, isRGB, chosenChannel);
    selectWindow(ft);
    rename("bgsample_" + IJ.pad(idx, 6));
    sampleTitles = Array.concat(sampleTitles, getTitle());
    idx = idx + step;
}
run("Images to Stack", "name=BGSampleStack title=bgsample use");
run("Z Project...", "projection=Median");
bgProjTitle = getTitle();
close("BGSampleStack");
print("Background built from " + sampleTitles.length + " sampled frames.");

// ---- Step 6: Determine ONE fixed threshold from a representative frame ----
// Exit batch mode temporarily for the interactive threshold check
setBatchMode(false);
calibFrame = getChannelFrame(origTitle, 1, isRGB, chosenChannel);
selectWindow(calibFrame);
imageCalculator("Difference", calibFrame, bgProjTitle);
selectWindow(calibFrame);
run("Gaussian Blur...", "sigma=" + gaussSigma);
// Restrict the threshold calculation to the arena only - otherwise the
// large blackened/irrelevant surrounding area would skew the histogram
// and produce a nonsense threshold (this was the original bug).
roiManager("Select", 0);
setAutoThreshold("Default dark");

// INTERACTIVE CHECK - don't just trust the automatic guess. This opens
// the live Threshold window so you can see and adjust the red overlay
// before it gets locked in and used for all frames. The overlay will
// also show red OUTSIDE the arena (e.g. over the ruler) - that's just
// the display painting every matching pixel in the whole image, and
// is normal; only what's INSIDE the arena selection actually matters,
// since that's the only region Analyze Particles will look at later.
run("Threshold...");
waitForUser("Check the threshold",
    "Look at the image behind this box.\n" +
    "The RED overlay INSIDE the dish should cover ONLY the larva\n" +
    "- not scattered noise or banding stripes.\n\n" +
    "If it looks noisy, drag the lower slider in the Threshold\n" +
    "window UP until the red cleans up to just the larva blob.\n\n" +
    "When it looks right, click OK here.");
getThreshold(threshLow, threshHigh);
if (isOpen("Threshold")) {
    selectWindow("Threshold");
    run("Close");
}
run("Select None");
close(calibFrame);
print("Fixed threshold (confirmed): " + threshLow + " - " + threshHigh);
if (threshLow < 10) {
    print("WARNING: threshold lower bound is very low (" + threshLow + ") - this often means residual noise will still be picked up as false particles. Consider increasing gaussSigma and re-running if results look noisy.");
}

// ---- Step 7: Frame-by-frame tracking (one small image in memory at a time) ----
// Re-enter batch mode for the heavy tracking loop
setBatchMode(true);
run("Set Measurements...", "area centroid center redirect=None decimal=3");

frameArr = newArray(numSlices);
xpxArr   = newArray(numSlices);
ypxArr   = newArray(numSlices);
areaArr  = newArray(numSlices);
foundArr = newArray(numSlices);

for (i = 1; i <= numSlices; i++) {
    ft = getChannelFrame(origTitle, i, isRGB, chosenChannel);
    selectWindow(ft);
    imageCalculator("Difference", ft, bgProjTitle);
    selectWindow(ft);
    run("Gaussian Blur...", "sigma=" + gaussSigma);
    // Restrict thresholding/particle counting to the arena only (same
    // reasoning as the calibration step above) - no need to blacken
    // anything, an active selection is enough to scope both operations.
    roiManager("Select", 0);
    setThreshold(threshLow, threshHigh);
    run("Analyze Particles...", "size=" + minSize + "-" + maxSize + " pixel circularity=0.00-1.00 clear display include");
    run("Select None");

    frameArr[i-1] = i;
    n = nResults;
    if (n == 0) {
        xpxArr[i-1] = NaN;
        ypxArr[i-1] = NaN;
        areaArr[i-1] = NaN;
        foundArr[i-1] = 0;
    } else {
        bestIdx = 0;
        bestArea = getResult("Area", 0);
        for (j = 1; j < n; j++) {
            a = getResult("Area", j);
            if (a > bestArea) {
                bestArea = a;
                bestIdx = j;
            }
        }
        // Center of mass (XM/YM) rather than geometric centroid (X/Y) -
        // intensity-weighted, giving a more accurate sub-pixel position
        // than treating every thresholded pixel as equally "larva".
        xpxArr[i-1] = getResult("XM", bestIdx);
        ypxArr[i-1] = getResult("YM", bestIdx);
        areaArr[i-1] = bestArea;
        foundArr[i-1] = 1;
    }
    close(ft);

    if (i % 500 == 0) print("Processed frame " + i + " / " + numSlices);
}
close(bgProjTitle);
// Exit batch mode before showing results
setBatchMode(false);

// ---- Step 8: Build output table (px + mm) and save ----
run("Clear Results");
for (i = 0; i < numSlices; i++) {
    setResult("Frame", i, frameArr[i]);
    setResult("Time_s", i, frameArr[i] / fps);
    setResult("X_px", i, xpxArr[i]);
    setResult("Y_px", i, ypxArr[i]);
    setResult("X_mm", i, xpxArr[i] * pxWidth);
    setResult("Y_mm", i, ypxArr[i] * pxHeight);
    setResult("Area_px", i, areaArr[i]);
    setResult("Detected", i, foundArr[i]);
    setResult("Arena_center_X_px", i, arenaCenterXPx);
    setResult("Arena_center_Y_px", i, arenaCenterYPx);
    setResult("Arena_center_X_mm", i, arenaCenterXMm);
    setResult("Arena_center_Y_mm", i, arenaCenterYMm);
    setResult("Arena_radius_px", i, arenaRadiusPx);
    setResult("Arena_radius_mm", i, arenaRadiusMm);
}
updateResults();

if (outputPath == "") {
    // Derive a clean base name from the input folder.
    // e.g.  N2_nSybxRalRNAi_L1_FA-0001_frames  ->  N2_nSybxRalRNAi_L1_FA
    // Strip the trailing path separator so File.getName works correctly.
    folderPath = substring(inputDir, 0, lengthOf(inputDir) - 1);
    folderName = File.getName(folderPath);
    // 1. Remove any trailing [-_]<digits>_frames  (e.g. -0001_frames)
    baseName = replace(folderName, "[-_][0-9]+_frames$", "");
    // 2. If only _frames remains (no preceding digits), remove that too
    baseName = replace(baseName, "_frames$", "");
    outputPath = inputDir + baseName + ".csv";
}
saveAs("Results", outputPath);

showMessage("Done", "Tracking complete.\nSaved to: " + outputPath +
            "\nLarval size used: " + minSize + "-" + maxSize + " px^2" +
            "\nThreshold used: " + threshLow + "-" + threshHigh +
            "\nFrames with no detection: check the 'Detected' column (0 = missed, fill in by interpolation if needed).");
