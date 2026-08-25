# Conflict of interest — null-ollama control

**This control was written by MCB's author, and it is the most damaging result
in the repository to MCB's own published comparison.**

`GOVERNANCE.md` §5 requires a disclosure from anyone who writes an adapter for a
system they do not maintain. The rule was written with the Letta adapter in
mind, where the author had an interest in the *comparison* looking a particular
way. It applies here for the opposite reason, and the disclosure is worth making
precisely because the incentive ran the other way.

## What this is

It is not an adapter. There is no system under test. It removes the memory
framework from the stack and measures what the model does on its own. Read
`README.md` in this directory for the mechanism, and `adapter.py` for the
roughly thirty lines of tool stubs that are the entire "memory system".

## The interest, stated plainly

MCB's author also authors AOMS, which was published in a comparison table
against Letta. That table showed Letta ahead. This control was run to find out
whether that gap was architecture or model, and it found that the framework's
measured contribution on this corpus is indistinguishable from zero — which
retires the comparison table the author's own system appeared in.

- **The direction of the result.** It destroys a published finding rather than
  supporting one. It removes a competitor's advantage, but it does not transfer
  that advantage to AOMS: the correct reading is that the comparison never
  measured what it claimed to measure, in either direction, so AOMS's 50.0% is
  not thereby vindicated. AOMS has been removed from the competitive tables as
  part of the same correction, and the author's system now sits in a
  non-competing appendix.
- **The result was published against interest, but by an interested party.** The
  same person chose the control's design, ran it, and wrote the conclusion. No
  one from Letta, and no independent third party, has reviewed it.

## What is not constrained, and should be read as open

- **The tool stubs are an approximation.** `memory_insert` and `memory_replace`
  here are local Python functions, not Letta's tools. They implement the same
  edit vocabulary against a plain string, including the verbatim-match failure
  mode, but they are a reimplementation and a different one would move the
  score. A reader who believes the stubs are too generous or too strict should
  change them and re-run; that is thirty lines of `adapter.py`.
- **The prompt is Letta's adapter's prompt, which was also written by MCB's
  author.** The control reads persona, separator and preamble verbatim from
  `../letta/config.json` so that the framework is the only difference between
  the stacks. That holds the prompt fixed; it does not make the prompt neutral.
  If the persona itself is what carries the score, this control cannot separate
  that from the model, and it does not claim to.
- **One model, one temperature, one corpus.** qwen3:8b at temperature 0 on 48
  frozen cases. This says nothing about how the gap between framework and bare
  model would behave with a different model, a longer corpus, retrieval under
  load, or any of the properties MCB explicitly does not measure. A control that
  matches a framework on 48 single-turn write decisions has not shown the
  framework is worthless; it has shown this benchmark cannot see its
  contribution.
- **A single run, and not a variance study.** The published artifact is one
  execution at temperature 0. Letta's published column is likewise a single run
  of a non-deterministic system. Neither has characterised spread, so **46/48
  should be read as a strong qualitative result about where the score comes
  from, not as a precise coefficient.** Two runs agreeing to the third decimal
  place would be better evidence than one, and it does not exist yet.
- **One earlier attempt produced no artifact and is disclosed rather than
  buried.** The first harness ran all 48 cases and then failed at the scoring
  step, because it omitted the per-case `inputs` echo the frozen scorer requires;
  it discarded every row and wrote nothing. A figure of "47 of 48" circulated
  from that attempt before anyone noticed it could not have been scored. The
  published figure is 46, from the fixed harness, reproduced from the committed
  artifact. See `../../CORRECTIONS.md` entry #2, "A correction inside the
  correction".

## What would strengthen it

Someone other than MCB's author running `adapter.py` unchanged against
`qwen3:8b` and getting the same figure. The artifact, the harness, the prompt
source and the environment record are all in this directory for exactly that
reason. Until that happens this control is asserted by its author, which is the
standard MCB holds other people's adapters to and must hold its own to.

Results: `README.md`, artifact `results-null-ollama-qwen3-8b.json`, verbatim
console output `runner-output.txt`. Correction entry:
`../../CORRECTIONS.md` (2026-08-25).
