# QA: client-proof.mp4

1920x1080 @ 30.000 fps, 48.97 s, audio: True

| level | check | detail |
|---|---|---|
| PASS | frame 0 | mean 192.1, contrast 72.9; still confirm it's a finished composition |
| PASS | hook text | 'A booking that doesn't match the request' at 0.6 s: ~273.6 px font (>= 84), contrast 11.9:1 (>= 7:1) |
| PASS | term text | 'Read-back: Air conditioning repair · Wed' at 15.1 s: ~184.7 px font (>= 48), contrast 11.6:1 (>= 7:1) |
| PASS | term text | 'lookup_customer → get_service_area → get' at 23.1 s: ~172.2 px font (>= 48), contrast 11.5:1 (>= 7:1) |
| PASS | cta text | 'Send two call flows.' at 42.8 s: ~250.0 px font (>= 48), contrast 11.9:1 (>= 7:1) |
| PASS | single-frame flashes | none |
| WARN | pops | small spikes at [5.6, 13.533, 14.4, 22.267, 22.533, 23.333, 23.433, 36.667, 41.133]: intended hits, or glitches/stray transitions? |
| PASS | cuts vs plan | max error 0.0 f; missing []; unplanned [] |
| WARN | frozen stretch | 0.23-5.33 s (5.1 s): designed hold or dead air? |
| WARN | frozen stretch | 6.0-7.27 s (1.27 s): designed hold or dead air? |
| WARN | frozen stretch | 7.4-13.37 s (5.97 s): designed hold or dead air? |
| WARN | frozen stretch | 14.6-21.4 s (6.8 s): designed hold or dead air? |
| WARN | frozen stretch | 24.07-28.4 s (4.33 s): designed hold or dead air? |
| WARN | frozen stretch | 29.77-36.67 s (6.9 s): designed hold or dead air? |
| WARN | frozen stretch | 38.07-41.13 s (3.07 s): designed hold or dead air? |
| WARN | frozen stretch | 42.0-48.9 s (6.9 s): final hold |
| WARN | flat frames | near-uniform frames at [{'from': 28.4, 'to': 29.27}, {'from': 36.67, 'to': 37.47}, {'from': 41.13, 'to': 41.53}]: blank transition frames? |
| PASS | loudness | -14.8 LUFS (target -14.0 +/-1), true peak -1.4 dBTP (<= -1.0) |
| INFO | loudest moment | loudest 100 ms at 6.3 s (-7.5 dBFS); voice clock: confirm the payoff hit is the loudest non-voice sound and sits in a VO pause |
| PASS | silence before peak | silences >= 0.4 s below -30.0 dBFS: [{'from': 3.75, 'to': 5.75}, {'from': 10.2, 'to': 10.75}, {'from': 12.65, 'to': 13.7}, {'from': 15.65, 'to': 16.25}, {'from': 20.65, 'to': 21.6}, {'from': 22.95, 'to': 23.55}, {'from': 25.25, 'to': 25.75}, {'from': 27.7, 'to': 28.7}] |

Sheets: qa/beats_sheet.jpg, qa/phone_sheet.jpg, qa/hook_sheet.jpg
Look at all three: numbers catch broken, not bad. The hook sheet is the muted test.
