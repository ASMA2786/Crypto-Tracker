#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import random
import time
import schedule
import smtplib
from time import sleep
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from elasticsearch import Elasticsearch
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Flask App Configuration
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_secret_key")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///market_data.db'
db = SQLAlchemy(app)

# Email Configuration
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.example.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

# Logging Configuration
logging.basicConfig(format='%(levelname)s: %(asctime)s - %(message)s', level=logging.INFO)

# Initialize Elasticsearch
ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
es = Elasticsearch(ELASTICSEARCH_URL)

# Price Alert Threshold
PRICE_THRESHOLD = float(os.getenv("PRICE_THRESHOLD", 50000))

# Market Refresh Rate
MARKET_REFRESH_RATE = int(os.getenv("MARKET_REFRESH_RATE", 30))  # 30 seconds

# Exchange Imports
from public.bitfinex import BitFinex_Market
from public.bitmex import BitMex_Market
from public.bittrex import BitTrex_Market
from public.gdax import GDAX_Market
from public.gemini import Gemini_Market
from public.kraken import Kraken_Market
from public.okcoin import OKCoin_Market
from public.poloniex import Poloniex_Market

# User Model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)  # Use hashed passwords in production

# Market Data Model
class MarketData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exchange = db.Column(db.String(50), nullable=False)
    product = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Function to Send Email Alerts
def send_email_alert(subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())

        logging.info(f"📩 Email alert sent: {subject}")
    except Exception as e:
        logging.error(f"❌ Failed to send email: {e}")

# Flask Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    market_data = MarketData.query.all()
    return render_template('dashboard.html', market_data=market_data)

@app.route('/plot/<string:exchange>/<string:product>')
def plot(exchange, product):
    data = MarketData.query.filter_by(exchange=exchange, product=product).all()
    prices = [d.price for d in data]
    timestamps = [d.timestamp for d in data]

    fig = Figure()
    axis = fig.add_subplot(1, 1, 1)
    axis.plot(timestamps, prices)
    axis.set_title(f"{product} prices on {exchange}")
    axis.set_xlabel('Timestamp')
    axis.set_ylabel('Price')

    return fig

# Main Market Data Collection
def main():
    db.create_all()

    logging.info(f"🚀 Market Tracker Started. Refresh Rate: {MARKET_REFRESH_RATE}s, Price Alert: {PRICE_THRESHOLD}")

    exchanges = [
        BitFinex_Market(), BitMex_Market(), BitTrex_Market(),
        GDAX_Market(), Gemini_Market(), Kraken_Market(),
        OKCoin_Market(), Poloniex_Market()
    ]

    # Log active exchanges
    for exchange in exchanges:
        logging.info(f"🔗 {exchange.exchange}: Connected")
        for product, kibana_index in exchange.products.items():
            if not es.indices.exists(index=kibana_index):
                es.indices.create(index=kibana_index)
            logging.info(f"📊 Index created for {product}")

    logging.warning("⚠️ Initiating Market Tracking...")

    while True:
        sleep(MARKET_REFRESH_RATE)
        try:
            for exchange in exchanges:
                exchange.record_ticker(es)
                for product in exchange.products:
                    price = exchange.get_price(product)
                    new_data = MarketData(exchange=exchange.exchange, product=product, price=price)
                    db.session.add(new_data)
                    db.session.commit()

                    logging.info(f"💰 {exchange.exchange} {product}: {price}")

                    if price > PRICE_THRESHOLD:
                        send_email_alert(
                            f"🚨 Price Alert: {product} on {exchange.exchange}",
                            f"The price of {product} has reached {price} on {exchange.exchange}"
                        )
        except Exception as e:
            logging.error(f"❌ Error in market tracking: {e}")
            sleep(10)  # Retry after 10 seconds

if __name__ == '__main__':
    main()
    app.run(debug=True)
