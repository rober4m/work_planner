# Calendar Work Planner - macOS 

## Requires: 

``` bash
conda create -n calendar python=3.11
```

``` bash
conda activate calendar
```

``` bash
pip install pyobjc-framework-EventKit
```

## Usage:

Only works using Terminal app of MacOS.
These examples add different times: 2d -> two days and 4h -> four hours.

```bash
python work_planner.py --project "Wind energy modelling" --time 2d --deadline 25-05  
```

```bash
python work_planner.py --project "Plot meteo data" --time 4h --deadline 30-05 
```