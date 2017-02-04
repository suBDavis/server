from flask import Flask, request, url_for, jsonify, redirect, Response, render_template
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_cors import CORS, cross_origin
from flask_oauth import OAuth
import random
import pickle
import datetime
import re

from mongoengine import DoesNotExist

from . import models
from . import facebookShim

#
# App init
#

app = Flask(__name__)
app.config['DEBUG'] = False
app.config['SECRET_KEY'] = settings.SECRET_KEY
CORS(app)

#
# Login init
#

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

#
# Oauth Handlers and Login
#

oauth = OAuth()
facebook = oauth.remote_app('facebook',
    base_url='https://graph.facebook.com/',
    request_token_url=None,
    access_token_url='/oauth/access_token',
    authorize_url='https://www.facebook.com/dialog/oauth',
    consumer_key=settings.FACEBOOK['APP_ID'],
    consumer_secret=settings.FACEBOOK['APP_SECRET'],
    request_token_params={'scope': 'email'}
)
fbshim = facebookShim.FacebookShim()

@login_manager.user_loader
def load_user(fb_id):
    try:
        return models.User.objects.get(fb_id=fb_id)
    except DoesNotExist:
        return None

@login_manager.request_loader
def load_user_from_request(request):

    # first, try to login using the api_key url arg
    api_key = request.args.get('api_key')
    if api_key:
        user = models.User.objects(api_key=api_key).first()
        if user:
            return user
        return None
    return None

# If local debug, bypass auth and assume the user is authenticated...
def get_local_user():
    name = "LocalUser"
    user = models.User.objects.filter(name=name).first()
    if not user:
        user = models.User()
        user.init(name, '0')
        user.save()
    return user

#
# Template Views
#


@app.route('/')
def index():
    return render_template('index.html')
#
# Private APIs
# 

@app.route('/api/me')
@login_required
def memes():
    return jsonify({
        "money": current_user.money,
        "stocks": current_user.get_holdings(),
        "api_key": current_user.api_key
    })

@app.route('/api/buy')
@login_required
def buy():
    meme = request.args.get("meme")
    stock = models.Stock.objects.filter(name=meme).first()
    if not stock:
        stock = models.Stock(name=meme, price=0, history=[])
        stock.save()

    if current_user.buy_one(stock):
        return success()
    return fail()


@app.route('/api/sell')
@login_required
def sell():
    meme = request.args.get("meme")
    stock = models.Stock.objects.filter(name=meme).first()
    if stock:
        if current_user.sell_one(stock):
            return success()
    return fail()

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

#
# Publically available APIS
# 

@app.route('/api/stock')
def stock():
    meme = request.args.get("meme")
    stock = models.Stock.objects.filter(name=meme).only('name','price','trend').first()
    if stock:
        return Response(stock.to_json(), mimetype="application/json")
    else:
        return jsonify({})


@app.route('/login')
def login():
    """ /login is hit before and after the user gets to facebook. """
    callback_base = settings.SERVER_NAME
    if app.config['DEBUG']:
        # bypass auth, just login the local user and go to index
        login_user(get_local_user())
        return redirect(url_for('index'))
    else:
        return facebook.authorize(callback=callback_base + url_for("oauth_authorized"))

@app.route('/oauth-authorized')
@facebook.authorized_handler
def oauth_authorized(resp):
    print("I was called?")
    next_url = url_for('index')
    if resp is None:
        flash(u'You denied the request to sign in.')
        return redirect(next_url)
    user_data = fbshim.get_user(resp['access_token'])
    user = load_user(user_data['user_id'])
    if not user:
        user = models.User()
        user.init(user_data['name'], user_data['user_id'])
        user.save()
    login_user(user)
    redirect_to_client = redirect(url_for('index'), code=302)
    response = app.make_response(redirect_to_client )  
    response.set_cookie('api_key',value=user.api_key)
    return response

@app.route('/api/stocks')
def stocks():
    all_stocks = models.Stock.objects.only('name','price','trend').order_by('-price')
    return Response(all_stocks.to_json(), mimetype="application/json")

@app.route('/api/history')
def history():
    print(request.url)
    meme = request.args.get("meme")
    stock = models.Stock.objects.filter(name=meme).first()
    ret = []
    if stock:
        for h in stock.history:
            ret.append({
                "price": h.price,
                "time": datetime.datetime.fromtimestamp(h.time)
            })

    return jsonify(ret)

@app.route('/api/recent')
def recent():   
    return jsonify(transactions[-100:])

#
# A few other helpers
#
def success():
    return jsonify({"status":"success"})

def fail():
    return jsonify({"status":"fail"})