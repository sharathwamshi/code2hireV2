// On-device face counting for proctoring. Works in every modern browser (Chrome, Edge, Firefox, Safari):
// a small TensorFlow.js model (190 KB, served from /models) runs locally. No video leaves the browser;
// only a small snapshot is sent when a warning is raised, so reviewers can see what happened.
let loading = null;

/** Resolves to count(video) -> number of faces, or null when no detector can run on this device. */
export function loadFaceCounter() {
  if (!loading) {
    loading = (async () => {
      try {
        const faceapi = await import("@vladmandic/face-api");
        try { await faceapi.tf.setBackend("webgl"); } catch { /* falls back to cpu/wasm */ }
        await faceapi.tf.ready();
        await faceapi.nets.tinyFaceDetector.loadFromUri("/models");
        const opts = new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.45 });
        return async (video) => (await faceapi.detectAllFaces(video, opts)).length;
      } catch (e) {
        // last resort: the browser's own detector, where it exists
        if ("FaceDetector" in window) {
          const fd = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 4 });
          return async (video) => (await fd.detect(video)).length;
        }
        return null;
      }
    })();
  }
  return loading;
}

/** A small JPEG of the current frame (320 px wide) for the integrity record. */
export function snapshot(video, width = 320) {
  try {
    if (!video || video.readyState < 2 || !video.videoWidth) return null;
    const h = Math.round((video.videoHeight / video.videoWidth) * width);
    const c = document.createElement("canvas"); c.width = width; c.height = h;
    c.getContext("2d").drawImage(video, 0, 0, width, h);
    return c.toDataURL("image/jpeg", 0.6);
  } catch { return null; }
}
