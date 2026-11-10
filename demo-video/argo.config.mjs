import { defineConfig } from '@argo-video/cli';
import { lfm3Engine } from './lfm3-engine.mjs';

export default defineConfig({
  baseURL: 'http://127.0.0.1:8000',
  demosDir: 'demos',
  outputDir: 'videos',
  tts: {
    engine: lfm3Engine({ voice: 'male', lang: 'en' }),
    defaultVoice: 'male',
    defaultSpeed: 0.98,
  },
  video: {
    width: 1920,
    height: 1080,
    fps: 30,
    browser: 'chromium',
    browserChannel: 'chrome',
    captureMode: 'jpeg-stitch',
    deviceScaleFactor: 2,
    cursorHighlight: {
      mode: 'click',
      color: '#2f7ed8',
      radius: 26,
      opacity: 0.85,
    },
  },
  export: {
    preset: 'slow',
    crf: 18,
    sharpen: true,
    audio: { loudnorm: true },
  },
  overlays: {
    autoBackground: true,
  },
});
