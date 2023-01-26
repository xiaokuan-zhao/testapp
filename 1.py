import os
import eikon as ek
import pandas as pd
eikon_api = os.getenv('refinitive_api')

ek.set_app_key(eikon_api)

df = ek.get_timeseries(["MSFT.O", "IVV"], start_date="2016-01-01", end_date="2016-01-10")

print(df['HIGH'])