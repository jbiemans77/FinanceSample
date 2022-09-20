import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime

from helpers import apology, login_required, lookup, usd


# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Global variable
startingFunds = 10000

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


# <---------------------------------------- Routes are below here

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    cash = getUserCash(session["user_id"])
    cashUSD = usd(cash)

    stocks = getUserStocks(session["user_id"], True)
    stockTotal = GetStockTotal(stocks)

    total = float(cash) + float(stockTotal)
    totalUSD = usd(total)

    return render_template("indexTable.html", stocks=stocks, cash=cashUSD, total=totalUSD)


@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()

    if not(request.method == "POST"):
        return render_template("login.html")
    else:
        username = request.form.get("username")
        password = request.form.get("password")

        errorMessage = ValidateUsername(username, True)
        if not(errorMessage == None):
            return apology(errorMessage, 403)

        errorMessage = ValidatePasswordAndConfirmation(username, password, password, True)
        if not(errorMessage) == None:
            return apology(errorMessage, 403)

        session["user_id"] = GetUserID(username)

        return redirect("/")


@app.route("/logout")
def logout():
    session.clear()

    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    if not(request.method == "POST"):
        return render_template("register.html")
    else:
        username = request.form.get("username")
        confirmation = request.form.get("confirmation")
        password = request.form.get("password")

        hash = generate_password_hash(password)

        errorMessage = ValidateUsername(username, False)
        if not(errorMessage == None):
            return apology(errorMessage)

        errorMessage = ValidatePasswordAndConfirmation(username, password, confirmation, False)
        if not(errorMessage) == None:
            return apology(errorMessage)

        AddUserToDatabase(username, hash)

        return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    if not(request.method == "POST"):
        return render_template("quote.html")
    else:
        symbol = request.form.get("symbol")

        errorMessage = ValidateSymbol(symbol)
        if not(errorMessage == None):
            return apology(errorMessage)

        stockDetails = lookup(symbol)
        if stockDetails == None:
            return apology("Invaild Symbol, please try again")

        name = stockDetails["name"]
        symbol = stockDetails["symbol"]
        price = stockDetails["price"]
        price = usd(price)

        return render_template("quoted.html", name=name, symbol=symbol, price=price)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    symbol = request.form.get("symbol")
    shares = request.form.get("shares")
    isFromIndex = bool(request.form.get("isFromIndex"))
    userID = session["user_id"]

    if not(request.method == "POST"):
        return render_template("buy.html")
    else:
        if isFromIndex == True:
            return render_template("buy.html", selectedSymbol=symbol)

        errorMessage = ValidateSymbol(symbol)
        if not(errorMessage == None):
            return apology(errorMessage)

        stockDetails = lookup(symbol)
        if stockDetails == None:
            return apology("Invaild Symbol, please try again")

        errorMessage = ValidateShares(shares)
        if not(errorMessage == None):
            return apology(errorMessage)

        cash = getUserCash(userID)
        transactionCost = stockDetails["price"] * int(shares)
        remainingFunds = float(cash - transactionCost)

        if 0 > remainingFunds:
            return apology("Sorry, you do not have enough cash on hand to complete the transaction.", 403)

        BuyOrSellShares(userID, stockDetails, shares, remainingFunds)

        flash("Bought!")
        return redirect("/")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    symbol = request.form.get("symbol")
    shares = request.form.get("shares")
    isFromIndex = bool(request.form.get("isFromIndex"))
    userID = session["user_id"]

    if not request.method == "POST":
        symbols = GetUserStockSymbols(userID)
        return render_template("sell.html", symbols=symbols)
    else:
        if isFromIndex == True:
            symbols = GetUserStockSymbols(userID)
            return render_template("sell.html", symbols=symbols, selectedSymbol=symbol)

        errorMessage = ValidateSymbol(symbol)
        if not(errorMessage == None):
            return apology(errorMessage)

        errorMessage = ValidateShares(shares)
        if not(errorMessage == None):
            return apology(errorMessage)

        shares = int(shares)
        ownedShareCount = GetShareCountForSymbol(userID, symbol)

        if ownedShareCount < shares:
            return apology("Sorry, you don't have enough shares to complete this sale")

        stockDetails = lookup(symbol)
        cash = getUserCash(userID)
        transactionCost = stockDetails["price"] * -int(shares)
        remainingFunds = float(cash - transactionCost)

        BuyOrSellShares(userID, stockDetails, -shares, remainingFunds)

        flash("Sold!")
        return redirect("/")


@app.route("/history")
@login_required
def history():
    stocks = getUserStocks(session["user_id"], False)
    return render_template("historyTable.html", stocks=stocks)


# <---------------------------------------------Functions are below here

class Stock:
    def __init__(self, symbol, name, shares, price, transactionTimeStamp, subTotal):
        self.symbol = symbol
        self.name = name
        self.shares = shares
        self.price = usd(price)
        self.transactionTimeStamp = transactionTimeStamp
        self.subTotal = usd(subTotal)


def getUserCash(userID):
    rows = db.execute("SELECT cash FROM users WHERE id = ?", userID)
    cash = rows[0]["cash"]
    print(f"cash {cash} row {rows[0]}")

    cash = round(cash, 2)
    return cash


def getUserStocks(userID, summary):
    stocks = []
    sharesOwnedVar = "numberOfSharesOwned, "
    purchasePriceVar = "purchasePrice, "
    groupByVar = ""

    if summary == True:
        sharesOwnedVar = "SUM(numberOfSharesOwned) as numberOfSharesOwned, "
        purchasePriceVar = "(SUM(purchasePrice) / numberOfSharesOwned) as purchasePrice, "
        groupByVar = "GROUP BY stockSymbol"

    rows = db.execute(
        "SELECT "
        "stockSymbol, "
        "stockName, " +
        sharesOwnedVar +
        purchasePriceVar +
        "transactionTimeStamp, "
        "subTotal "
        "FROM holdings "
        "WHERE user_id = ? "
        + groupByVar + "", userID)

    for row in rows:
        stockPriceVar = row["purchasePrice"]

        if summary == True:
            symbol = row["stockSymbol"]

            stockDetails = lookup(symbol)
            if stockDetails == None:
                return apology("Invaild Symbol, please try again")

            stockPriceVar = stockDetails["price"]

        stock = Stock(row["stockSymbol"],
                      row["stockName"],
                      row["numberOfSharesOwned"],
                      stockPriceVar,
                      row["transactionTimeStamp"],
                      row["subTotal"])
        stocks.append(stock)

    return stocks


def GetStockTotal(stocks):
    stockTotal = 0

    for stock in stocks:
        stockSubtotal = stock.subTotal.replace("$", "")
        stockSubtotal = stockSubtotal.replace(",", "")

        stockTotal += float(stockSubtotal)

    return stockTotal


def GetUserStockSymbols(userID):
    symbols = []
    rows = db.execute(
        "SELECT "
        "DISTINCT stockSymbol "
        "FROM holdings "
        "WHERE user_id = ?", userID)

    for row in rows:
        symbols.append(row["stockSymbol"])

    print(symbols)

    return symbols


def GetShareCountForSymbol(userID, symbol):
    totalShareCount = db.execute("SELECT SUM(numberOfSharesOwned) as totalShareCount FROM holdings WHERE stockSymbol = ?", symbol)

    return totalShareCount[0]["totalShareCount"]


def GetUserID(username):
    rows = db.execute("SELECT * FROM users WHERE username = ?", username)

    return rows[0]["id"]


def AddUserToDatabase(username, hash):
    db.execute("INSERT INTO users (username, hash, cash) VALUES(?, ?, ?)", username, hash, startingFunds)
    rows = db.execute("SELECT * FROM users WHERE username = ?", username)
    session["user_id"] = rows[0]["id"]


def BuyOrSellShares(userID, stockDetails, shares, remainingFunds):
    symbol = stockDetails["symbol"]
    stockName = stockDetails["name"]
    price = stockDetails["price"]
    timeStamp = datetime.now()
    subTotal = float(shares) * float(price)

    db.execute(
        "INSERT INTO holdings ("
        "user_id, "
        "stockSymbol, "
        "stockName, "
        "numberOfSharesOwned, "
        "purchasePrice, "
        "transactionTimeStamp, "
        "subTotal)"
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        userID,
        symbol,
        stockName,
        shares,
        price,
        timeStamp,
        subTotal)

    db.execute("UPDATE users SET cash=? WHERE id=?", remainingFunds, userID)


# <------------------------------------------------Form validation functions below here

def ValidateUsername(username, isLogin):
    errorMessage = None

    if username == "":
        errorMessage = "Username was blank, please try again."
    else:
        if not isLogin:
            rows = db.execute("SELECT * FROM users WHERE username = ?", username)

            for row in rows:
                if row["username"] == username:
                    errorMessage = "Sorry, username already exists."
        # else:
            # Additional complexity checks for password can be added here.

    return errorMessage


def ValidatePasswordAndConfirmation(username, password, confirmation, isLogin):
    errorMessage = None

    if password == "":
        errorMessage = "Password was blank, please try again."
    elif confirmation == "":
        errorMessage = "Confirmation was blank, please try again."
    elif not(password == confirmation):
        errorMessage = "Password did not match confirmation, please try again."
    else:
        errorMessage = None

    if isLogin:
        rows = db.execute("SELECT * FROM users WHERE username = ?", username)

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
            errorMessage = "Incorrect password"

    return errorMessage


def ValidateSymbol(symbol):
    errorMessage = None

    if symbol == "":
        errorMessage = "Sorry, the symbol field was blank, please try again."

    return errorMessage


def ValidateShares(shares):
    errorMessage = None

    if shares == None or shares == "":
        errorMessage = "You must enter a number into the shares field"
    elif shares.isnumeric():
        shares = int(shares)
        if shares < 0:
            errorMessage = "Sorry the number must be greater than 0."
        elif not(shares % 1 == 0):
            errorMessage = "Sorry, only whole shares can be purchased."
    else:
        errorMessage = "Sorry somehow you broke the form and entered text in a number field!"

    return errorMessage