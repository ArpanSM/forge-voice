# QA: voice-walkthrough.mp4

1920x1080 @ 30.000 fps, 74.43 s, audio: True

| level | check | detail |
|---|---|---|
| PASS | frame 0 | mean 227.8, contrast 16.9; still confirm it's a finished composition |
| PASS | single-frame flashes | none |
| WARN | pops | small spikes at [1.2, 1.333, 1.433, 1.533, 1.633, 1.767, 1.833, 1.967, 2.067, 2.167, 2.267, 2.4, 2.467, 2.6, 2.667, 2.8, 2.867, 3.0, 3.133, 3.233, 3.367, 3.433, 3.767, 4.667, 8.367, 8.467, 8.667, 8.767, 8.867, 9.0, 9.067, 9.2, 9.267, 11.733, 12.233, 13.8, 14.6, 24.6, 26.367, 26.567, 27.067, 34.367, 36.333, 37.067, 37.667, 47.267, 69.667]: intended hits, or glitches/stray transitions? |
| INFO | detected cuts | [8.033, 8.167, 8.233, 8.567, 11.8, 11.933, 12.0, 12.133, 13.867, 13.967, 14.067, 14.2, 14.267, 14.4, 14.533, 22.0, 22.133, 23.867, 23.967, 24.067, 24.2, 24.267, 24.4, 24.467, 26.433, 26.667, 26.767, 26.867, 26.967, 30.967, 33.767, 33.833, 33.967, 34.067, 34.167, 34.267, 36.4, 36.533, 36.633, 36.767, 36.833, 36.967, 37.367, 37.467, 37.567, 43.933, 46.467, 46.567, 46.667, 46.767, 46.867, 46.967, 47.067, 47.167, 51.467, 51.633, 58.633, 69.433] |
| WARN | frozen stretch | 6.2-7.93 s (1.73 s): designed hold or dead air? |
| WARN | frozen stretch | 10.03-11.53 s (1.5 s): designed hold or dead air? |
| WARN | frozen stretch | 12.63-13.8 s (1.17 s): designed hold or dead air? |
| WARN | frozen stretch | 14.83-22.0 s (7.17 s): designed hold or dead air? |
| WARN | frozen stretch | 24.93-26.37 s (1.43 s): designed hold or dead air? |
| WARN | frozen stretch | 27.4-30.97 s (3.57 s): designed hold or dead air? |
| WARN | frozen stretch | 31.47-33.77 s (2.3 s): designed hold or dead air? |
| WARN | frozen stretch | 34.6-36.33 s (1.73 s): designed hold or dead air? |
| WARN | frozen stretch | 37.87-43.63 s (5.77 s): designed hold or dead air? |
| WARN | frozen stretch | 44.07-46.47 s (2.4 s): designed hold or dead air? |
| WARN | frozen stretch | 47.47-51.47 s (4.0 s): designed hold or dead air? |
| WARN | frozen stretch | 51.63-53.33 s (1.7 s): designed hold or dead air? |
| WARN | frozen stretch | 53.33-58.63 s (5.3 s): designed hold or dead air? |
| WARN | frozen stretch | 60.37-69.43 s (9.07 s): designed hold or dead air? |
| WARN | frozen stretch | 70.6-74.37 s (3.77 s): final hold |
| PASS | loudness | -15.0 LUFS (target -14.0 +/-1), true peak -1.3 dBTP (<= -1.0) |
| INFO | loudest moment | loudest 100 ms at 34.9 s (-7.5 dBFS); is this the payoff? |
| PASS | silence before peak | silences >= 0.4 s below -30.0 dBFS: [{'from': 6.4, 'to': 6.9}, {'from': 11.05, 'to': 12.0}, {'from': 13.85, 'to': 14.45}, {'from': 15.0, 'to': 15.45}, {'from': 20.55, 'to': 22.15}, {'from': 23.3, 'to': 24.0}, {'from': 26.6, 'to': 27.15}, {'from': 28.15, 'to': 28.65}] |

Sheets: qa/walkthrough/beats_sheet.jpg, qa/walkthrough/phone_sheet.jpg, qa/walkthrough/hook_sheet.jpg
Look at all three: numbers catch broken, not bad. The hook sheet is the muted test.
