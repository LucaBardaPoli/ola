import argparse
import numpy as np
import random
import matplotlib.pyplot as plt

import agents as ag
import environments as envi
import auctions as au
from utils import *

class Requirement1:
    def __init__(self, args, n_iters):
        self.args = args
        #extract all args in members
        for key, value in vars(args).items():
            setattr(self, key, value)

        #pricing members
        self.T_pricing = self.num_days

        #bidding members
        self.auctions_per_day = [self.auctions_per_day for _ in range(self.num_days)] 
        self.auctions_per_day = [int(i + np.random.uniform(-5, 5)) for i in self.auctions_per_day] #add noise 

        self.competitors_per_day = [100 for _ in range(self.num_days)]

        if self.ctrs is None:
            self.ctrs = np.random.uniform(0.4, 0.9, self.num_competitors+1)
        else:
            assert len(self.ctrs) == self.num_competitors+1, "Number of CTRs must match number of bidders"

        self.T_bidding = np.sum(self.auctions_per_day)

    def main(self):

        ''' PRICING SETUP '''
        item_cost = 0.1
        min_price = item_cost
        max_price = 1

        # a round of pricing for each day
        T_pricing = self.num_days
        eps = T_pricing ** (-1 / 3)
        # discretization step from theory
        K = int(1/eps + 1)

        discr_prices = np.linspace(min_price, max_price, K)
        pricing_agent = ag.GPUCBAgent(T_pricing, K)
        # parametric conversion probability   
        theta = 1     
        conversion_probability = lambda p: (1 - p/max_price) ** theta
        pricing_envir = envi.StochasticPricingEnvironment(conversion_probability, item_cost)

        ''' BIDDING SETUP '''
        num_competitors = self.num_competitors
        my_budget = 1000

        min_bid = 0
        max_bid = 1

        # a round of bidding for each auction
        T_bidding = np.sum(self.auctions_per_day)  
        eps = T_bidding ** (-1 / 3)
        # discretization step from theory
        K = int(1/eps + 1)

        available_bids = np.linspace(min_bid, max_bid, K)
        # learning rate from theory
        eta = 1 / np.sqrt(T_bidding)
        my_ctr = self.ctrs[0]
        my_valuation = 0.8

        other_bids = lambda n: np.random.beta(10, 7, n)

        bidding_envir = envi.StochasticBiddingCompetitors(other_bids, num_competitors)
        auction = au.SecondPriceAuction(self.ctrs)
        if self.bidder_type == 'UCB':
            bidding_agent = ag.UCB1BiddingAgent(my_budget, available_bids, T_bidding)
        elif self.bidder_type == 'pacing':
            bidding_agent = ag.StochasticPacingAgent(my_valuation, my_budget, T_bidding, eta)
        else:
            print("Invalid bidder type")
            exit(1)

        total_sales = 0
        total_profit = 0
        
        total_wins = 0
        total_utility = 0
        total_spent = 0

        for t in range(self.num_days):
            ### Pricing phase: choose the price at the start of the day
            price_t = pricing_agent.pull_arm()

            day_wins = 0
            n_clicks = 0
            ### Bidding phase: each auction is a user connecting to the site where the ad slot is displayed
            for auction_index in range(self.auctions_per_day[t]):
                
                bid_t = bidding_agent.bid()
                other_bids_t = bidding_envir.round()
                m_t = other_bids_t.max()
                bids = np.append(bid_t, other_bids_t)

                winner, payment_per_click = auction.round(bids)

                my_win = 0
                if winner == 0: # auction won
                    my_win = 1
                    day_wins += 1

                    user_clicked = np.random.binomial(1, self.ctrs[0])
                    n_clicks += user_clicked
                    # each click on the ad will result in a pricing round

                # utility and cost for the bidding agent are computed             
                f_t = (my_valuation - payment_per_click) * my_win
                c_t = payment_per_click * my_win
                bidding_agent.update(f_t, c_t)

                total_utility += f_t
                total_spent += c_t

            ### Pricing phase: updating the price at the end of the day
            # get bandit feedback from environment
            d_t, r_t = pricing_envir.round(price_t, n_clicks)
            # update pricing agent
            pricing_agent.update(r_t/n_clicks if n_clicks>0 else 0)

            # update sales and profit on the played price
            day_sales = d_t
            day_profit = r_t

            total_wins += day_wins
            total_sales += day_sales
            total_profit += day_profit

            print(f"Day {t+1}: Price: {price_t}, Day wins: {day_wins}, N.clicks: {n_clicks}, Day Sales: {day_sales}, Day Profit: {day_profit}")

        print(f"Total wins: {total_wins}, Total utility: {total_utility}, Total spent: {total_spent}, Total sales: {total_sales}, Total profit: {total_profit}")

    
    ''' ONLY BIDDING '''
    def bidding(self):

        num_competitors = self.num_competitors
        my_budget = 500
        # in this case we are just considering bidding so no need to separate for the different days.
        n_auctions = sum(self.auctions_per_day)
        # discretization step from theory
        eps = n_auctions**(-1/3)
        K = int(1/eps + 1)
        # learning rate from theory
        eta = 1/np.sqrt(n_auctions)
        
        my_ctr = self.ctrs[0]
        other_ctrs = self.ctrs[1:]
        my_valuation = 0.8

        # WLOG we assume bids to be in [0,1]
        available_bids = np.linspace(0, 1, K)
        other_bids = lambda n: np.random.beta(40, 27, n)
        # with alpha=40 and beta=27 the distribution is centered around 0.6

        envir = envi.StochasticBiddingCompetitors(other_bids, num_competitors)
        auction = au.SecondPriceAuction(self.ctrs)

        if self.bidder_type == 'UCB':
            agent = ag.UCB1BiddingAgent(my_budget, available_bids, n_auctions)
        elif self.bidder_type == 'pacing':
            agent = ag.StochasticPacingAgent(my_valuation, my_budget, n_auctions, eta)
        else:
            print("Invalid bidder type")
            exit(1)
        
        my_utilities = np.array([])
        my_bids = np.array([])
        my_payments = np.array([])
        m_ts = np.array([])
        
        total_wins = 0
        total_utility = 0
        total_spent = 0
        for t in range(n_auctions):
            # agent chooses bid
            bid_t = agent.bid()
            # get bids from other competitors
            other_bids_t = envir.round()
            m_t = other_bids_t.max()

            bids = np.append(bid_t, other_bids_t)
            winner, payments_per_click = auction.round(bids)
            my_win = (winner == 0)
            f_t = (my_valuation - m_t) * my_win
            c_t = m_t * my_win
            # update agent
            agent.update(f_t, c_t)

            ''' LOGGING '''
            my_utilities = np.append(my_utilities, f_t)
            my_bids = np.append(my_bids, bid_t)
            my_payments = np.append(my_payments, c_t)
            m_ts = np.append(m_ts, m_t)

            total_wins += my_win
            total_utility += f_t
            total_spent += c_t

            print(f"Auction: {t+1}, Bid: {bid_t}, Opponent bid: {m_t}, Utility: {f_t}, Payment: {c_t}, Winner: {winner}")

        print(f"Total wins: {total_wins}, Total utility: {total_utility}, Total spent: {total_spent}")

        ''' CLAIRVOYANT '''
        clairvoyant_bids, clairvoyant_utilities, clairvoyant_payments = get_clairvoyant_truthful(my_budget, my_valuation, m_ts, n_auctions)

        # plot_clayrvoyant_truthful(my_budget, clairvoyant_bids, clairvoyant_utilities, clairvoyant_payments)

        ''' AGENT '''
        plot_agent_bidding(my_budget, my_bids, my_utilities, my_payments)

        ''' REGRET '''
        plot_regret(my_utilities, clairvoyant_utilities)

    ''' ONLY PRICING '''
    def pricing(self):
        
        item_cost = 0.1
        min_price = item_cost # anything lower than this would be a loss
        max_price = 1 # price at which the conversion probability is 0
        n_customers = 100

        # discretization step from theory
        eps = self.T_pricing**(-1/3)
        K = int(1/eps)
        if K % 2 == 0:
            K += 1 # this ensures K is odd

        discr_prices = np.linspace(min_price, max_price, K)

        conversion_probability = lambda p: 1 - p/max_price
        # such that the probability of conversion is 1 at price = 0 and 0 at price = max_price

        reward_function = lambda price, n_sales: (price - item_cost) * n_sales

        # the maximum possible profit is selling to all customers at the maximum price for which the conversion probability is > 0
        max_reward = max_price * n_customers

        print(f"Max Reward: {max_reward}, Discretized Prices: {discr_prices}, K: {K}")
        
        ''' CLAIRVOYANT '''
        expected_profit_curve = n_customers * conversion_probability(discr_prices) * (discr_prices-item_cost)
        best_price_index = np.argmax(expected_profit_curve)

        expected_clairvoyant_rewards = np.repeat(np.ceil(expected_profit_curve[best_price_index]), self.T_pricing)

        n_trials = 10
        regret_per_trial = []

        for seed in range(n_trials):
            np.random.seed(seed)

            agent = ag.GPUCBAgent(T = self.T_pricing, discretization = K)
            envir = envi.StochasticPricingEnvironment(conversion_probability, item_cost)

            my_prices = np.array([])
            my_sales = np.array([])
            my_rewards = np.array([])
            total_sales = 0
            total_profit = 0

            for t in range(self.T_pricing): 
                # GP agent chooses price
                price_t = agent.pull_arm()
                # rescale price from [0,1] to [min_price, max_price]
                price_t = denormalize_zero_one(price_t, min_price, max_price)

                # get demand and reward from pricing environment
                d_t, r_t = envir.round(price_t, n_customers)
                # reward = total profit

                # update agent with profit normalized to [0,1]
                agent.update(normalize_zero_one(r_t, 0, max_reward))

                ''' LOGGING '''
                my_prices = np.append(my_prices, price_t)
                my_sales = np.append(my_sales, d_t)
                my_rewards = np.append(my_rewards, r_t)

                total_sales += d_t
                total_profit += r_t

                print(f"Day {t+1}: Price: {price_t}, Demand: {d_t}, Reward: {r_t}")

            print(f"Total Sales: {total_sales}, Total Profit: {total_profit}")

            cumulative_regret = np.cumsum(expected_clairvoyant_rewards - my_rewards)
            regret_per_trial.append(cumulative_regret)

        regret_per_trial = np.array(regret_per_trial)
        average_regret = regret_per_trial.mean(axis=0)
        regret_sd = regret_per_trial.std(axis=0)

        plt.plot(np.arange(self.T_pricing), average_regret, label='Average Regret')
        plt.title('cumulative regret of UCB1')
        plt.fill_between(np.arange(self.T_pricing),
                        average_regret-regret_sd/np.sqrt(n_trials),
                        average_regret+regret_sd/np.sqrt(n_trials),
                        alpha=0.3,
                        label='Uncertainty')
        #plt.plot((0,T-1), (average_regret[0], average_regret[-1]), 'ro', linestyle="--")
        plt.xlabel('$t$')
        plt.legend()
        plt.show()

        plot_agent_pricing(my_prices, my_sales, my_rewards)

        plot_regret(my_rewards, expected_clairvoyant_rewards)

        # plot_demand_curve(discr_prices, conversion_probability, n_customers)

        # plot_profit_curve(discr_prices, conversion_probability, n_customers, item_cost)
        

        

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_days", dest="num_days", type=int, default=365)
    parser.add_argument("--auctions_per_day", dest="auctions_per_day", type=int, default = 10)
    parser.add_argument("--n_iters", dest="n_iters", type = int, default=100)
    parser.add_argument("--num_competitors", dest="num_competitors", type=int, default=10)
    parser.add_argument("--ctrs", dest = "ctrs", type=list, default = None)
    parser.add_argument("--seed", dest="seed", type=int, default=11)
    parser.add_argument("--run_type", dest="run_type", type=str, choices=['main', 'bidding', 'pricing'], default='pricing')
    parser.add_argument("--bidder_type", dest="bidder_type", type=str, choices=['UCB', 'pacing'], default='UCB-like')

    #for pricing only
    parser.add_argument("--num_buyers", dest="num_buyers", type = int, default = 100)

    args = parser.parse_args()    

    set_seed(args.seed)

    req = Requirement1(args, 100)

    if args.run_type == 'main':
        req.main()
    elif args.run_type == 'bidding':
        req.bidding()
    elif args.run_type == 'pricing':
        req.pricing()
    else:
        print("Invalid run type")
        exit(1)
    