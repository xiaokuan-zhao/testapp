from dash import Dash, html, dcc, dash_table, Input, Output, State
import eikon as ek
import pandas as pd
import numpy as np
from datetime import datetime, date
import plotly.express as px
import os
import statsmodels.api as sm

ek.set_app_key(os.getenv('refinitive_api'))

app = Dash(__name__)
# The app.layout is take in python and generate an html
app.layout = html.Div([
    html.Div([
        html.Label("Benchmark:"),
        dcc.Input(id = 'benchmark-id', type = 'text', value="IVV"),
        html.Label("Asset:"),
        dcc.Input(id = 'asset-id', type = 'text', value="AAPL.O"),
        html.Label("Date Range: "),
        dcc.DatePickerRange(
            id='my-date-picker-range',
            month_format='MMM Do, YY',
            end_date_placeholder_text='MMM Do, YY',
            start_date_placeholder_text='MMM Do, YY')
    ]),
    html.Button('QUERY Refinitiv', id = 'run-query', n_clicks = 0),
    html.H2('Raw Data from Refinitiv'),
    dash_table.DataTable(
        id = "history-tbl",
        page_action='none',
        style_table={'height': '300px', 'overflowY': 'auto'}
    ),
    html.H2('Historical Returns'),
    dash_table.DataTable(
        id = "returns-tbl",
        page_action='none',
        style_table={'height': '300px', 'overflowY': 'auto'}
    ),
    dcc.DatePickerRange(
        id='date-for-plot',
        month_format='MMM Do, YY',
        end_date_placeholder_text='MMM Do, YY',
        start_date_placeholder_text='MMM Do, YY'),
    html.Button('draw graph', id = 'draw_graph', n_clicks = 0),
    html.H2('Alpha & Beta Scatter Plot'),
    dcc.Graph(id="ab-plot"),
    html.P(id='summary-text', children=""),
    html.H2('Here is the parameter'),
    html.Div(id = 'sentence')
])
# this callback is used to update the output the data:history data when you do something.
# It is kind of like function in excel
# introducing a global variable
@app.callback(
    Output("history-tbl", "data"),
    Input("run-query", "n_clicks"), # not going to do anything until the query button is clicked
    [State('benchmark-id', 'value'), State('asset-id', 'value'), Input('my-date-picker-range', 'start_date'),Input('my-date-picker-range', 'end_date')],
    prevent_initial_call=True # do not want it to run immediately when it initialize
    # what is the difference between state and input: when you do input(click), something triggers, but state
    # give you the value
)
# to make sure clicks, runs
def query_refinitiv(n_clicks, benchmark_id, asset_id, start_date ,end_date):
    assets = [benchmark_id, asset_id]
    prices, prc_err = ek.get_data(
        instruments=assets,
        fields=[
            'TR.OPENPRICE(Adjusted=0)',
            'TR.HIGHPRICE(Adjusted=0)',
            'TR.LOWPRICE(Adjusted=0)',
            'TR.CLOSEPRICE(Adjusted=0)',
            'TR.PriceCloseDate'
        ],
        parameters={
            'SDate': start_date,
            'EDate': end_date,
            'Frq': 'D'
        }
    )

    divs, div_err = ek.get_data(
        instruments=assets,
        fields=[
            'TR.DivExDate',
            'TR.DivUnadjustedGross',
            'TR.DivType',
            'TR.DivPaymentType'
        ],
        parameters={
            'SDate': start_date,
            'EDate': end_date,
            'Frq': 'D'
        }
    )

    splits, splits_err = ek.get_data(
        instruments=assets,
        fields=['TR.CAEffectiveDate', 'TR.CAAdjustmentFactor'],
        parameters={
            "CAEventType": "SSP",
            'SDate': start_date,
            'EDate': end_date,
            'Frq': 'D'
        }
    )

    prices.rename(
        columns={
            'Open Price': 'open',
            'High Price': 'high',
            'Low Price': 'low',
            'Close Price': 'close'
        },
        inplace=True
    )
    prices.dropna(inplace=True)
    prices['Date'] = pd.to_datetime(prices['Date']).dt.date

    divs.rename(
        columns={
            'Dividend Ex Date': 'Date',
            'Gross Dividend Amount': 'div_amt',
            'Dividend Type': 'div_type',
            'Dividend Payment Type': 'pay_type'
        },
        inplace=True
    )
    divs.dropna(inplace=True)
    divs['Date'] = pd.to_datetime(divs['Date']).dt.date
    divs = divs[(divs.Date.notnull()) & (divs.div_amt > 0)]

    splits.rename(
        columns={
            'Capital Change Effective Date': 'Date',
            'Adjustment Factor': 'split_rto'
        },
        inplace=True
    )
    splits.dropna(inplace=True)
    splits['Date'] = pd.to_datetime(splits['Date']).dt.date

    unadjusted_price_history = pd.merge(
        prices, divs[['Instrument', 'Date', 'div_amt']],
        how='outer',
        on=['Date', 'Instrument']
    )
    unadjusted_price_history['div_amt'].fillna(0, inplace=True)

    unadjusted_price_history = pd.merge(
        unadjusted_price_history, splits,
        how='outer',
        on=['Date', 'Instrument']
    )
    unadjusted_price_history['split_rto'].fillna(1, inplace=True)

    if unadjusted_price_history.isnull().values.any():
        raise Exception('missing values detected!')
    global dictionary
    dictionary = unadjusted_price_history.to_dict('records')
    return(unadjusted_price_history.to_dict('records'))



@app.callback(
    Output("returns-tbl", "data"),
    Input("history-tbl", "data"),
    prevent_initial_call = True
)
def calculate_returns(history_tbl):

    dt_prc_div_splt = pd.DataFrame(history_tbl)

    # Define what columns contain the Identifier, date, price, div, & split info
    ins_col = 'Instrument'
    dte_col = 'Date'
    prc_col = 'close'
    div_col = 'div_amt'
    spt_col = 'split_rto'

    dt_prc_div_splt[dte_col] = pd.to_datetime(dt_prc_div_splt[dte_col])
    dt_prc_div_splt = dt_prc_div_splt.sort_values([ins_col, dte_col])[
        [ins_col, dte_col, prc_col, div_col, spt_col]].groupby(ins_col)
    numerator = dt_prc_div_splt[[dte_col, ins_col, prc_col, div_col]].tail(-1) # deal with dividens
    denominator = dt_prc_div_splt[[prc_col, spt_col]].head(-1) #deal with the split
# calculating the returns
    return(
        pd.DataFrame({
        'Date': numerator[dte_col].reset_index(drop=True),
        'Instrument': numerator[ins_col].reset_index(drop=True),
        'rtn': np.log(
            (numerator[prc_col] + numerator[div_col]).reset_index(drop=True) / (
                    denominator[prc_col] * denominator[spt_col]
            ).reset_index(drop=True)
        )
    }).pivot_table(
            values='rtn', index='Date', columns='Instrument'
        ).to_dict('records')
    )

@app.callback(
    Output("ab-plot", "figure"),
    [State('benchmark-id', 'value'), State('asset-id', 'value'), Input("draw_graph", "n_clicks"), Input('date-for-plot', 'start_date'),
      Input('date-for-plot', 'end_date')],
    prevent_initial_call = True
)
def render_ab_plot(benchmark_id, asset_id, n_clicks, start_date, end_date):
    returns = pd.DataFrame(dictionary)
    ins_col = 'Instrument'
    dte_col = 'Date'
    prc_col = 'close'
    div_col = 'div_amt'
    spt_col = 'split_rto'
    returns[dte_col] = pd.to_datetime(returns[dte_col])
    returns = returns[(returns[dte_col] >= pd.to_datetime(start_date)) & (returns[dte_col] <= pd.to_datetime(end_date))]
    returns = returns.sort_values([ins_col, dte_col])[
        [ins_col, dte_col, prc_col, div_col, spt_col]].groupby(ins_col)
    numerator = returns[[dte_col, ins_col, prc_col, div_col]].tail(-1) # deal with dividens
    denominator = returns[[prc_col, spt_col]].head(-1) #deal with the split
    outcome = pd.DataFrame({
        'Date': numerator[dte_col].reset_index(drop=True),
        'Instrument': numerator[ins_col].reset_index(drop=True),
        'rtn': np.log(
            (numerator[prc_col] + numerator[div_col]).reset_index(drop=True) / (
                    denominator[prc_col] * denominator[spt_col]
            ).reset_index(drop=True)
        )
    }).pivot_table(
            values='rtn', index='Date', columns='Instrument'
        ).to_dict('records')
    # Define your data points
    x = []
    y = []
    for i in outcome:
        y.append(i["AAPL.O"])
        x.append(i["IVV"])
    # Add a constant to your independent variable
    x = sm.add_constant(x)

    # Fit the model using OLS
    model = sm.OLS(y, x).fit()

    # Get the parameters
    params = model.params
    global intercept
    intercept = params[0]
    global slope
    slope = params[1]

    return(
        px.scatter(outcome, x=benchmark_id, y=asset_id, trendline='ols'))


@ app.callback(
    Output("sentence", "children"),
    Input("ab-plot", "figure"),
    prevent_initial_call=True
)
def printline(ab_plot):
    stri = ''
    stri = stri + 'The Beta is ' + str(slope) + ', and the Alpha is ' + str(intercept)
    return stri

if __name__ == '__main__':
    app.run_server(debug=True)