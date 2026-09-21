# Provenance

CascadeShift separates maintained prototype code from completed historical evidence. The v1 archive
and its frozen engine remain historical material. Documentation and measurement-interface changes
do not change the v1 result.

The v1.2.1 source snapshot is `ad1bbedd8b8fd9ab9540608130775017484a5c6d`. Version 1.3.0 was
prepared from reviewed source commit `9b21b97f252e0d01054abb972d0658ba194338c5`, whose Git tree is
`383ff993a1dccc8e71791e52ef014d803f1204be`. That source commit is an assembly anchor, not a
frozen scientific protocol. `scripts/check_artifacts.py` verifies the
[exact retained v1 scope](docs/artifact-scope.md) and the 450-episode archive. The historical
`protocol/freeze_manifest.json` applies to v1 only; it does not verify every file in version 1.3.0.

The public candidate has a new, single-commit Git history and the repository metadata URL
<https://github.com/jlov7/CascadeShift-Research>. Version 1.3.0 adds offline verification scripts
and the separate measurement-v2 development module. Neither addition is part of the historical
study.

The archived local model/runtime label is `qwen3.8-27b`. It used an Unsloth Q6_K_XL GGUF conversion based on `Qwen/Qwen3.8-27B`, as named by the [pinned model card](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/blob/4ca720788d1e01f1bff70c033e0d0028fd02e502/README.md).

| Historical local artifact | SHA-256 | Pinned public metadata |
| --- | --- | --- |
| Main Q6_K_XL GGUF | `701d8fa9ed214ab21bfc130cd2a7df19ca89bbef7713e2dfb19f3c63696aa917` | [Qwen3.8-27B-UD-Q6_K_XL.gguf](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/blob/4ca720788d1e01f1bff70c033e0d0028fd02e502/Qwen3.8-27B-UD-Q6_K_XL.gguf) |
| Projection GGUF | `cbb841a9ee0636b2ec172f5bb8df2ea8dfeb01e90fe7c6126581d662a0b4e43e` | [mmproj-F16.gguf](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/blob/4ca720788d1e01f1bff70c033e0d0028fd02e502/mmproj-F16.gguf) |

The hashes identify those local quantized files. They do not establish equivalence to full-precision upstream weights or behavior beyond the archived runtime.

AI tools assisted with implementation, drafting, and automated checks. Those checks do not
constitute independent peer review. Errors and limitations remain the author's responsibility.

The repository retains deterministic evidence needed for the stated checks. It does not publish
raw provider diagnostic records from measurement v2. The v2 summary is source-derived and has the
limitations stated in [Results](RESULTS.md).
