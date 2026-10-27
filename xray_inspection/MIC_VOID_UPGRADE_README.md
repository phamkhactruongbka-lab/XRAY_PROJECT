# MIC VOID – XRAY DREAMTECH (experimental integration)

Run from `xray_inspection` on Windows after installing requirements: `python main.py`.

**New:** MIC Void button in AUTO screen, editable threshold 0–100% (0.5% step), separate MIC confidence, crop PNG and CSV per batch, ROI coordinates and polarity. Settings saved to `config_roi.json`. Stop AUTO before editing.

**Safety:** Existing YOLO NG classification is deliberately retained for ALL detections, including MIC void. Measured OK never overrides NG and never authorizes robot movement. A missing/invalid solder ROI yields REVIEW. The rectangular ROI and Otsu segmentation are EXPERIMENTAL, not validated metrology. Do not use the displayed void percentage as a production acceptance criterion without calibrated X-Ray images, verified solder masks, inspection standard, and validation against ground truth.

**Output:** `C:/XRAY_STORAGE/BATCH_*/MIC_VOID_CROPS/` and `mic_void_results.csv` when enabled. The CSV reports the experimental measurement, not the production decision.

**Known limitations:** One rectangular ROI is shared across images and may not align with all MIC positions. Per-position calibrated ROI and mark registration are required for production-grade measurements. Original system's source-image deletion and robot handshake were not changed; review those separately before deployment. Test on an offline Windows workstation before connecting Dobot.
