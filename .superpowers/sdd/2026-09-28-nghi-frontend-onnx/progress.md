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
