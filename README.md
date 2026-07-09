# Trend Sniper AI v8.1 Scheduled Scan

Workflow ogni 5 minuti, ma analisi allineata alla chiusura delle candele.

## Timeframe
- 5M: ogni 5 minuti
- 15M: ogni 15 minuti
- 1H: ogni ora
- 4H: ogni 4 ore

## File generati
- `signals.csv`: segnali inviati
- `last_scan.json`: ultimo scan eseguito

## Heartbeat
Ogni ora il bot manda un messaggio Telegram "Trend Sniper AI online".

Per spegnerlo:

```python
HEARTBEAT_ENABLED = False
```

## Test Telegram
Nel file `trend_sniper.py`:

```python
TEST_MODE = True
```

Dopo il test rimetti:

```python
TEST_MODE = False
```
