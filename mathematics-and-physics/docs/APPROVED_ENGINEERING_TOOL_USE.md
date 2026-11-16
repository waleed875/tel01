# Explicitly approved model-to-engineering-tool workflow (Issue #30)

The small, locally trained text GPT can **propose** that a deterministic
engineering tool verify a calculation. It cannot call, run, or authorize
engineering tools itself. The proposed operation is treated as untrusted model
output, not as a command. Nothing is automatically committed to Gitea or
executed as a program.

The system is dedicated only to engineering software, maths, electronics and
physics, and continues to use our own local models (no OpenAI API, pretrained
weights or MinIO).

## Suggested response protocol

A trained model may include a single fenced JSON tool request in its text:

```engineering-tool
{"operation":"physics.force","inputs":{"mass":3,"acceleration":4}}
```

Only one block is accepted. Exact allowlisted operation identifiers and their
required input names must match `engineering_calculators.OPERATIONS`. Any
unsupported operation, missing or additional argument, nonfinite value,
negative mass, unsafe size or other invalid assumption is rejected. The model
does not gain Python execution, network access or Gitea write permissions.

## Review and approval sequence

1. The user enters a question in normal engineering chat.
2. A locally trained GPT checkpoint generates an ordinary text answer. If its
   output contains one valid `engineering-tool` block, the server checks the
   proposed operation and input structure, and confirms that the operation
   belongs to the user's currently selected engineering domain.
3. The web interface shows the exact operation and inputs in a separate
   review panel. The result is **not** executed or displayed yet.
4. The user explicitly clicks **أوافق على المدخلات — احسب الآن** and accepts a
   confirmation dialog.
5. The server checks the logged-in user's identity, a server-signed HMAC bound
   to the operation/inputs/user and its 10-minute expiration.
6. The deterministic engineering calculator returns independently computed
   values, formula and physical assumptions. The verified result is clearly
   distinguished from the initial model-generated answer.

The signed token is per running web-process instance and is intentionally lost
on restart. Old suggestions must be regenerated and reviewed again after
restart or expiry. In a multi-worker deployment, the ephemeral key would need
an appropriate shared lifecycle; current Docker config uses one worker.

## What this does **not** mean

- No proof the model reliably generates correctly formatted proposals.
- No proof it chooses the correct tool or extracts correct values.
- A tool result is accurate **only for the provided inputs and assumptions**.
- Wrong quantities or units entered/proposed by the model can yield
  mathematically correct but irrelevant results. Review input units.
- Python AST analysis never executes user-submitted source. General code
  execution remains owner-operated in a separate Docker-only CLI.
- There is no automatic model rewrite of its original message after seeing
  tool output. The user's trusted evidence is the separate deterministic
  result with its formula and assumptions.
- This feature does not send questions to online models, download pretrained
  checkpoints, or add additional AI domains.

## Next quality milestones

- Run trained local checkpoints through representative unseen questions to
  quantify model-proposal detection, correct tool selection, input extraction
  and verified-result quality separately.
- Compare errors in maths, physics and electronics before and after
  approval-driven tool use.
- Add more engineering solvers with rigorous dimensional analysis and
  uncertainty propagation, retaining an allowlisted operator protocol.
- Test end-to-end browser behavior on the user's own trusted local Docker
  installation, and review authorization/CSRF controls before public access.
