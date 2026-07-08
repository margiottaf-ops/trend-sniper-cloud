# Trend Sniper AI v7 TEST

Scanner gratuito con GitHub Actions + Telegram.

## Attivo
- 4H = principale
- 1H = test secondario
- 15M = solo test rapido
- 5M = solo pratica/rumore

## Telegram
Ogni alert contiene:
- simbolo
- timeframe
- BUY/SELL
- score
- entry
- stop loss
- TP1, TP2, TP3, TP4
- rischio
- lotto/unità indicativo
- motivo del segnale

## Journal automatico
Ogni segnale inviato viene salvato in:

`signals.csv`

## Test Telegram
Nel file `trend_sniper.py`:

```python
TEST_MODE = True
```

fai commit e lancia workflow.

Dopo il test rimetti:

```python
TEST_MODE = False
```

## Regola
Solo conto demo.  
Non usare il 5M per decidere trade reali: serve solo per test/pratica.
