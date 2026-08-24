# Stage 2: using it in anger

**Template. Fill it in as you go, not at the end.** The point of
Stage 2 is the half that measurement cannot reach: whether the
patterns hold up on work someone actually had to do.

## How to turn the log on

```bash
export CODE_STEWARD_FIELD_LOG="$HOME/.code-steward-field.jsonl"
```

One JSON line per invocation: the command, its exit code, how long it
took, how many members a slice came back with, whether it was empty,
and which selector produced it. Nothing else, nowhere else -- the
file is local and this project never reads it off your machine.

**Private repositories are the point of this stage and the reason for
the rule.** The log names units and paths from whatever repository
you ran in. It is not committed, and nothing derived from it reaches
this repository except counts and sanitised observations.

## The two questions

Everything below is in service of these. Answer them in specifics --
a command, a moment, an outcome -- not in impressions.

### What did it catch?

Something you would have missed, or would have spent longer finding.
Record the command, what came back, and what you did differently.

| Date | Command | What it caught | Would you have found it otherwise? |
| --- | --- | --- | --- |
|  |  |  |  |

### What did it waste time on?

An empty slice you trusted, a duplicate that was not one, a command
you ran and then ignored, a bundle you read and could not use.
**This table failing to fill up is a warning sign, not a good sign.**

| Date | Command | What it cost | Why it happened |
| --- | --- | --- | --- |
|  |  |  |  |

## What gets published from this

Counts and patterns only:

- Invocations by command, and the share that came back empty.
- How often `--members-from` was used and whether it beat plain
  `trace` in practice.
- The two tables above, rewritten without private identifiers.

No paths, no unit names, no snippets, no repository names.

## The exit

A written account containing **both** halves. An account with an
empty second table has not met the exit criterion; it has only
recorded that nobody wrote the second table.
