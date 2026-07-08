# Trend Sniper AI v6 - Multi-Timeframe TEST

Scanner gratuito con GitHub Actions + Telegram.

## Timeframe attivi
- 4H = principale
- 1H = test secondario
- 15M = solo test rapido
- 5M = solo pratica / rumore

## Regola operativa
Usare tutto solo su conto demo.  
Il 4H resta il riferimento principale.  
1H, 15M e 5M servono per raccogliere dati e confrontare statistiche nel Journal.

## Test Telegram
Nel file `trend_sniper.py`:

```python
TEST_MODE = True
```

poi fai commit e lancia workflow.

Dopo il test rimetti:

```python
TEST_MODE = False
```

## Nota
Ogni alert Telegram indica sempre il timeframe.
