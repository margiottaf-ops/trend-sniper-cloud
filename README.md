# Trend Sniper AI v8 SIMPLE TEST

Versione semplificata per partire in demo.

## Attivo
- 4H = principale
- 1H = test secondario
- 15M = solo test rapido
- 5M = solo pratica/rumore

## Messaggio Telegram
Ogni alert contiene solo:
- BUY / SELL
- timeframe
- entry
- stop loss
- take profit finale 1:4
- lotto/unità indicativo
- motivo del segnale

## Journal automatico
Ogni segnale inviato viene salvato in:

`signals.csv`

## Journal manuale
Usa il file Excel separato per segnare ingresso, esito e note.

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
Niente TP multipli e niente break-even nella prima fase.
