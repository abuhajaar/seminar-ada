# Per-Bar Artifacts

Set `run.dump_bar_artifacts: true` in `config.yaml`. After a run, every
candle that the engine processed has its own folder under
`results/runs/<RUN_ID>/<SAFE_SYMBOL>/bars/<NNNN>/` containing:

| File                       | Source              | What it is                                     |
|----------------------------|---------------------|------------------------------------------------|
| `input_indicators.json`    | Traditional bot     | Indicator scalars fed into the SuperTrend rule |
| `output_signal.json`       | Traditional bot     | Final Action / confidence / reasoning / stop   |
| `technical_input.txt`      | LLM bot (Technical) | Rendered prompt sent to the technical analyst  |
| `technical_output.json`    | LLM bot (Technical) | Raw response text from the analyst             |
| `visual_input.txt`         | LLM bot (Visual)    | Rendered prompt sent to the visual analyst     |
| `visual_input.png`         | LLM bot (Visual)    | The exact candlestick image the visual agent saw |
| `visual_output.json`       | LLM bot (Visual)    | Raw response text                              |
| `qabba_input.txt`          | LLM bot (QABBA)     | Rendered prompt for the QABBA analyst          |
| `qabba_output.json`        | LLM bot (QABBA)     | Raw response text                              |
| `decision_output.json`     | LLM bot (Decision)  | Final action + confidence + regime-gate state  |

Folder numbering is 1-based and zero-padded to the width of the total bar
count for the run, i.e. `len(str(total_bars))` digits. A 480-bar run uses
`001` ... `480`; a 65-bar run uses `01` ... `65`. Bars dropped during warmup
or by the NaN guard still get a folder — the indicator file contains the
partial scalars, and the LLM files are absent because the graph was not
invoked.
