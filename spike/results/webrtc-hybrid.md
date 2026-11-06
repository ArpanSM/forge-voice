# WebRTC bench — hybrid

- 10-turn first audio: p50 **2868 ms**, p95 **5345 ms**.
- Per turn: [2820, 4061, 2912, 2038, 4965, 2704, 2823, 5058, 5580, 2620]
- False interruptions: 0.

- Barge-in yield: **880 ms**; recovered: True.
- Overlapping speech events: 0; false interruptions: 0.

- Silence: prompted=False, recovered=True, first audio=2133 ms.

| Degradation | First audio | ZIP | Address | Phone | Transcript |
|---|---:|---|---|---|---|
| noisy | 1055 ms | False | True | True | I need a drain cleaning. My name is Sam Rivera. My address is 12 Alder Street, Nader 40-07. My phone |
| lowmic | 1093 ms | False | True | True | I need a drain cleaning. My name is Sam Rivera. My address is 12 Alder Street, Nadri 40 O said. My p |
| packetloss | 1111 ms | False | True | True | I need a drain cleaning. My name is Sam Rivera. My address is 12 Alder Street, Nadri 40 Ode. My phon |
