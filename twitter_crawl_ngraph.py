# -*- coding: utf-8 -*-
"""

Source : Twitter cookbook
@author: Satwik Hosamani
"""

import twitter
import sys
import time
from urllib.error import URLError
from http.client import BadStatusLine

from functools import partial
from sys import maxsize as maxint
import operator

import networkx as nx
import matplotlib.pyplot as plt

# Go to http://dev.twitter.com/apps/new to create an app and get values
# for these credentials, which you'll need to provide in place of these
# empty string values that are defined as placeholders.
# See https://developer.twitter.com/en/docs/basics/authentication/overview/oauth
# for more information on Twitter's OAuth implementation.

CONSUMER_KEY = 'g2RIGsIxzMH5vOsDpnsBhw11C'
CONSUMER_SECRET = 'asCuQPQxKONFBAe30RHjuKHBHZZfMnT3RslQgao5KKMF1dO3I7'
OAUTH_TOKEN = '740233862-ulciuzk5fAkaQFrct5yiHXwphYeuBAwgJ4ZVUXF5'
OAUTH_TOKEN_SECRET = '31STjyEzg5A3ome756R7WAPGYatEt4xulWI3gCvSYwRdJ'

auth = twitter.oauth.OAuth(OAUTH_TOKEN, OAUTH_TOKEN_SECRET,
                           CONSUMER_KEY, CONSUMER_SECRET)

twitter_api = twitter.Twitter(auth=auth)

print(twitter_api)


def make_twitter_request(twitter_api_func, max_errors=10, *args, **kw):
    # A nested helper function that handles common HTTPErrors. Return an updated
    # value for wait_period if the problem is a 500 level error. Block until the
    # rate limit is reset if it's a rate limiting issue (429 error). Returns None
    # for 401 and 404 errors, which requires special handling by the caller.
    def handle_twitter_http_error(e, wait_period=2, sleep_when_rate_limited=True):

        if wait_period > 3600:  # Seconds
            print('Too many retries. Quitting.', file=sys.stderr)
            raise e

        # See https://developer.twitter.com/en/docs/basics/response-codes
        # for common codes

        if e.e.code == 401:
            print('Encountered 401 Error (Not Authorized)', file=sys.stderr)
            return None
        elif e.e.code == 404:
            print('Encountered 404 Error (Not Found)', file=sys.stderr)
            return None
        elif e.e.code == 429:
            print('Encountered 429 Error (Rate Limit Exceeded)', file=sys.stderr)
            if sleep_when_rate_limited:
                print("Retrying in 15 minutes...ZzZ...", file=sys.stderr)
                sys.stderr.flush()
                time.sleep(60 * 15 + 5)
                print('...ZzZ...Awake now and trying again.', file=sys.stderr)
                return 2
            else:
                raise e  # Caller must handle the rate limiting issue
        elif e.e.code in (500, 502, 503, 504):
            print('Encountered {0} Error. Retrying in {1} seconds'.format(e.e.code, wait_period), file=sys.stderr)
            time.sleep(wait_period)
            wait_period *= 1.5
            return wait_period
        else:
            raise e

    wait_period = 2
    error_count = 0

    while True:
        try:
            return twitter_api_func(*args, **kw)
        except twitter.api.TwitterHTTPError as e:
            error_count = 0
            wait_period = handle_twitter_http_error(e, wait_period)
            if wait_period is None:
                return
        except URLError as e:
            error_count += 1
            time.sleep(wait_period)
            wait_period *= 1.5
            print("URLError encountered. Continuing.", file=sys.stderr)
            if error_count > max_errors:
                print("Too many consecutive errors...bailing out.", file=sys.stderr)
                raise
        except BadStatusLine as e:
            error_count += 1
            time.sleep(wait_period)
            wait_period *= 1.5
            print("BadStatusLine encountered. Continuing.", file=sys.stderr)
            if error_count > max_errors:
                print("Too many consecutive errors...bailing out.", file=sys.stderr)
                raise


def get_friends_followers_ids(twitter_api, screen_name=None, user_id=None,
                              friends_limit=maxint, followers_limit=maxint):
    # Must have either screen_name or user_id (logical xor)
    assert (screen_name != None) != (user_id != None), "Must have screen_name or user_id, but not both"

    # See http://bit.ly/2GcjKJP and http://bit.ly/2rFz90N for details
    # on API parameters

    get_friends_ids = partial(make_twitter_request, twitter_api.friends.ids,
                              count=5000)
    get_followers_ids = partial(make_twitter_request, twitter_api.followers.ids,
                                count=5000)

    friends_ids, followers_ids = [], []

    for twitter_api_func, limit, ids, label in [
        [get_friends_ids, friends_limit, friends_ids, "friends"],
        [get_followers_ids, followers_limit, followers_ids, "followers"]
    ]:

        if limit == 0: continue

        cursor = -1
        while cursor != 0:

            # Use make_twitter_request via the partially bound callable...
            if screen_name:
                response = twitter_api_func(screen_name=screen_name, cursor=cursor)
            else:  # user_id
                response = twitter_api_func(user_id=user_id, cursor=cursor)

            if response is not None:
                ids += response['ids']
                cursor = response['next_cursor']

            print('Fetched {0} total {1} ids for {2}'.format(len(ids), label, (user_id or screen_name)),
                  file=sys.stderr)

            # XXX: You may want to store data during each iteration to provide an
            # an additional layer of protection from exceptional circumstances

            if len(ids) >= limit or response is None:
                break

    # Do something useful with the IDs, like store them to disk...
    return friends_ids[:friends_limit], followers_ids[:followers_limit]


def crawl_followers(twitter_api, screen_name, G, limit=1000000, depth=2, **mongo_conn_kw):
    # Resolve the ID for screen_name and start working with IDs for consistency
    # in storage
    next_queue = [screen_name]
    d = 1
    #Performing a level by level search
    while d <= depth:
        d += 1
        (queue, next_queue) = (next_queue, [])
        for sname in queue:
            # Resolve the ID for screen_name and start working with IDs for consistency
            # in storage
            seed_id = str(twitter_api.users.show(screen_name=sname)['id'])
            # Get set of friends and followers
            friends_ids, followers_ids = get_friends_followers_ids(twitter_api, screen_name=sname,
                                                                   friends_limit=5000, followers_limit=5000)
            # Reciprocal friends are those who have each other as friends and followers
            reciprocal_friends = list(set(friends_ids).intersection(followers_ids))[0:15]
            reciprocal_info = make_twitter_request(twitter_api.users.lookup, user_id=reciprocal_friends)
            rec_friends_dict = {}

            if reciprocal_info is not None:
                for acc in reciprocal_info:
                    rec_friends_dict[acc['screen_name']] = acc['followers_count']

            # Sorting and listing only the screen names in descending order of followers count
            sorted_rec_friends_dict = dict(sorted(rec_friends_dict.items(), key=operator.itemgetter(1), reverse=True))
            next_queue = list(sorted_rec_friends_dict.keys())[0:5]  # Picking top 5 users based on the follower count
            # Create graph for each user relation found
            for usr in next_queue:
                G.add_node(usr)
                G.add_edge(sname, usr)


G = nx.Graph()
screen_name = "letspushpixels"
crawl_followers(twitter_api,screen_name,G, depth = 5) #Depth 5 gives us close to 100 nodes.


#displaying the network graph
nx.draw_networkx(G, with_labels=True, font_weight='bold')
# Writing the output in a txt file

f = open("output.txt","w")
f.write("Assignment-2 Social Netowrk\n")
f.write("Number of nodes: "+str(nx.number_of_nodes(G))+"\n")
f.write("Number of edges "+str(nx.number_of_edges(G))+"\n")
f.write("Average distance of network "+str(nx.average_shortest_path_length(G))+"\n")
f.write("Average diameter of network "+str(nx.diameter(G))+"\n")
f.close()