# SDD ledger — plan: docs/superpowers/plans/2026-09-28-nghi-frontend-onnx.md
Pre-flight: Task 1 produces {processed_text,chunks[].phoneme_ids}; Task 2 consumes the same contract — consistent with spec.
Pre-flight: Task 2 produces ID-only WAV synthesis; Task 3 only changes runtime discovery/launch — consistent with spec.
Pre-flight: Tasks 4–6 consume the same runtime/protocol without changing it — consistent with spec.
Ruling: GitHub Actions is the RED/GREEN executor because this harness cannot clone/run the repository locally; add contract commands to branch CI as tests are introduced. Production behavior remains unchanged by this ruling.
Task 1: complete (RED run #91 failed with ERR_MODULE_NOT_FOUND for tts/nghi_frontend.mjs; GREEN run #92 passed Python + Node regression including test_nghi_frontend.mjs; production commit 97606eb).
Task 2: Ruling: the legacy audit imported prepare_spoken_name, which Task 5 will replace; keep a temporary case-preserving whitespace helper so the full suite stays importable without reintroducing lowercase behavior into production.
Task 2: complete (RED run #94 failed on missing NghiFrontendClient/NghiOnnxSynthesizer; first GREEN attempt #95 passed all new worker tests but exposed the legacy audit import; GREEN run #96 passed full Python + Node regression; production commits d73ce83, 6cf92c9).
Task 3: Ruling: first GREEN run #99 showed production command was correct; one test asserted a patched module constant after leaving the patch context. Fixed the test to retain expected path values; no production change was made for that failure.
Task 3: complete (RED run #98 failed only on cache v5/missing NGHI runtime constants; GREEN run #100 passed full Python + Node regression; production commit 57b8eca).
Task 4: Rulings: setup verifies Node portable ZIP against Node's official SHASUMS256.txt before extraction; uses portable npm.cmd for npm ci; exact NGHI commit is verified with git -C <root> rev-parse HEAD. Two GREEN attempts exposed only overly literal test matchers, not setup defects; assertions were corrected without weakening the runtime contract.
Task 4: complete (RED run #102 failed only old setup/check scripts; final GREEN run #106 passed full Python + Node regression; setup commits 4914433, 1303ada; test corrections c60a779, c773558).
Task 5: complete (RED run #108 failed on missing compare_frontend_parity and legacy native-Piper audit script; GREEN run #110 passed full suite after replacing audit with pinned NGHI oracle vs production sidecar exact parity checks; commits 6fe66f0, 7c6160a).
