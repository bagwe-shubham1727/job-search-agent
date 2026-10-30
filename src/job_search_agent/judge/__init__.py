"""Claude judge: payloads, prompt contract, CLI backend, strict validator, retry.

Public entry points for other workstreams:

* ``judge.judge.CliJudge`` — the ``ports.Judge`` adapter for the pipeline (WS3);
  ``judge.judge.build_judge`` wires it from ``[model]`` settings.
* ``judge.judge.probe_model`` — one tiny real call for ``jsa doctor --probe-model``.
* ``judge.validator.validate_reply`` — the CONTRACT §8 validator.
"""
