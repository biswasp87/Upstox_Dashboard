import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np

# Load the data
df = pd.read_csv('option_chain_all_stocks.csv')
stocks = sorted(df['stock_name'].unique())

def calculate_max_pain(stock_df):
    strikes = sorted(stock_df['strike_price'].unique())
    total_loss = []

    for strike in strikes:
        loss = 0
        # Calls
        calls = stock_df[(stock_df['option_type'] == 'CE')]
        for _, row in calls.iterrows():
            if strike > row['strike_price']:
                loss += (strike - row['strike_price']) * row['market_oi']

        # Puts
        puts = stock_df[(stock_df['option_type'] == 'PE')]
        for _, row in puts.iterrows():
            if strike < row['strike_price']:
                loss += (row['strike_price'] - strike) * row['market_oi']

        total_loss.append(loss)

    max_pain = strikes[np.argmin(total_loss)]
    return max_pain

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("Upstox Option Chain Dashboard", className="text-center my-4"), width=12)
    ]),

    dbc.Row([
        dbc.Col([
            dbc.ButtonGroup([
                dbc.Button("Previous", id="prev-btn", color="primary"),
                dcc.Dropdown(
                    id='stock-dropdown',
                    options=[{'label': s, 'value': s} for s in stocks],
                    value=stocks[0] if stocks else None,
                    style={'width': '300px'}
                ),
                dbc.Button("Next", id="next-btn", color="primary"),
            ], className="d-flex align-items-center")
        ], width=6, className="mx-auto d-flex justify-content-center mb-4")
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4("Max Pain", className="card-title text-center"),
                    html.H2(id="max-pain-value", className="text-center text-danger"),
                    html.P(id="underlying-price-value", className="text-center font-weight-bold")
                ])
            ], className="mb-4 shadow-sm")
        ], width=4, className="mx-auto")
    ]),

    dbc.Row([
        dbc.Col(dcc.Graph(id='iv-graph'), width=12),
        dbc.Col(dcc.Graph(id='pcr-graph'), width=12),
        dbc.Col(dcc.Graph(id='oi-graph'), width=12),
        dbc.Col(dcc.Graph(id='change-oi-graph'), width=12),
        dbc.Col(dcc.Graph(id='volume-graph'), width=12),
    ])
], fluid=True)

@app.callback(
    Output('stock-dropdown', 'value'),
    Input('prev-btn', 'n_clicks'),
    Input('next-btn', 'n_clicks'),
    State('stock-dropdown', 'value')
)
def navigate_stocks(prev_clicks, next_clicks, current_stock):
    ctx = callback_context
    if not ctx.triggered:
        return current_stock

    btn_id = ctx.triggered[0]['prop_id'].split('.')[0]
    idx = stocks.index(current_stock)

    if btn_id == 'prev-btn':
        new_idx = (idx - 1) % len(stocks)
    elif btn_id == 'next-btn':
        new_idx = (idx + 1) % len(stocks)
    else:
        return current_stock

    return stocks[new_idx]

@app.callback(
    [Output('iv-graph', 'figure'),
     Output('pcr-graph', 'figure'),
     Output('oi-graph', 'figure'),
     Output('change-oi-graph', 'figure'),
     Output('volume-graph', 'figure'),
     Output('max-pain-value', 'children'),
     Output('underlying-price-value', 'children')],
    [Input('stock-dropdown', 'value')]
)
def update_graphs(selected_stock):
    if not selected_stock:
        return [go.Figure()] * 5 + ["", ""]

    stock_df = df[df['stock_name'] == selected_stock].copy()
    underlying_price = stock_df['underlying_spot_price'].iloc[0]
    max_pain = calculate_max_pain(stock_df)

    # 1. IV Graph
    fig_iv = go.Figure()
    ce_df = stock_df[stock_df['option_type'] == 'CE']
    pe_df = stock_df[stock_df['option_type'] == 'PE']

    # Eliminate zero volatility data
    ce_iv_df = ce_df[ce_df['greek_iv'] > 0]
    pe_iv_df = pe_df[pe_df['greek_iv'] > 0]

    fig_iv.add_trace(go.Scatter(
        x=ce_iv_df['strike_price'],
        y=ce_iv_df['greek_iv'],
        name='Call IV',
        line=dict(color='green', shape='spline')
    ))
    fig_iv.add_trace(go.Scatter(
        x=pe_iv_df['strike_price'],
        y=pe_iv_df['greek_iv'],
        name='Put IV',
        line=dict(color='red', shape='spline')
    ))
    fig_iv.add_vline(x=underlying_price, line_dash="dash", line_color="blue", annotation_text="Underlying")

    # Filter for 6 strikes above and below underlying
    all_strikes = sorted(stock_df['strike_price'].unique())
    atm_strike = min(all_strikes, key=lambda x: abs(x - underlying_price))
    atm_idx = all_strikes.index(atm_strike)

    start_idx = max(0, atm_idx - 6)
    end_idx = min(len(all_strikes), atm_idx + 7) # +7 because end is exclusive
    selected_strikes = all_strikes[start_idx:end_idx]

    fig_iv.update_layout(
        title="IV of Call and Put (6 Strikes Around ATM)",
        xaxis_title="Strike Price",
        yaxis_title="IV",
        xaxis=dict(
            tickmode='array',
            tickvals=selected_strikes,
            ticktext=[str(s) for s in selected_strikes],
            range=[min(selected_strikes), max(selected_strikes)]
        )
    )

    # 2. PCR Graph
    fig_pcr = go.Figure()
    fig_pcr.add_trace(go.Scatter(x=stock_df['strike_price'].unique(), y=stock_df.groupby('strike_price')['pcr'].first(), name='PCR'))
    fig_pcr.add_vline(x=underlying_price, line_dash="dash", line_color="blue", annotation_text="Underlying")
    fig_pcr.update_layout(title="PCR at each Strike Price", xaxis_title="Strike Price", yaxis_title="PCR")

    # 3. OI Graph
    fig_oi = go.Figure()
    fig_oi.add_trace(go.Bar(x=ce_df['strike_price'], y=ce_df['market_oi'], name='Call OI', marker_color='green'))
    fig_oi.add_trace(go.Bar(x=pe_df['strike_price'], y=pe_df['market_oi'], name='Put OI', marker_color='red'))
    fig_oi.add_vline(x=underlying_price, line_dash="dash", line_color="blue", annotation_text="Underlying")
    fig_oi.update_layout(title="Open Interest", barmode='group', xaxis_title="Strike Price", yaxis_title="OI")

    # 4. Change in OI Graph
    fig_change_oi = go.Figure()
    fig_change_oi.add_trace(go.Bar(x=ce_df['strike_price'], y=ce_df['market_change_oi'], name='Call Change OI', marker_color='lightgreen'))
    fig_change_oi.add_trace(go.Bar(x=pe_df['strike_price'], y=pe_df['market_change_oi'], name='Put Change OI', marker_color='salmon'))
    fig_change_oi.add_vline(x=underlying_price, line_dash="dash", line_color="blue", annotation_text="Underlying")
    fig_change_oi.update_layout(title="Change in Open Interest", barmode='group', xaxis_title="Strike Price", yaxis_title="Change OI")

    # 5. Volume Graph
    fig_volume = go.Figure()
    fig_volume.add_trace(go.Bar(x=ce_df['strike_price'], y=ce_df['market_volume'], name='Call Volume', marker_color='blue'))
    fig_volume.add_trace(go.Bar(x=pe_df['strike_price'], y=pe_df['market_volume'], name='Put Volume', marker_color='orange'))
    fig_volume.add_vline(x=underlying_price, line_dash="dash", line_color="blue", annotation_text="Underlying")
    fig_volume.update_layout(title="Volume", barmode='group', xaxis_title="Strike Price", yaxis_title="Volume")

    return fig_iv, fig_pcr, fig_oi, fig_change_oi, fig_volume, f"{max_pain}", f"Underlying Price: {underlying_price}"

if __name__ == '__main__':
    app.run(debug=False, port=8050, host='0.0.0.0')
