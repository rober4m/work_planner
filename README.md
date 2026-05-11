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

Only works using Terminal app of MacOS

```bash
python work_planner.py --project "heat island modelling" --time 2d --deadline 25-05  # Adding two days to the Heat island modelling project
```

```bash
python work_planner.py --project "Plot meteo data" --time 4h --deadline 30-05  # Adding four hours to plot data 
```