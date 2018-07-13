import time
init_ststus = {}


class Robot():

    def __init__(self, exchanges, check_try_time, spreads, max_sell, min_sell, min_blance, max_loss, slippage):
        self.exchanges = exchanges
        self.checkTryTime = check_try_time
        self.spreads = spreads
        self.maxSell = max_sell
        self.minSell = min_sell
        self.maxLoss = max_loss
        self.minBlance = min_blance
        self.slippage = slippage

        self.ORDER_STATE_PENDING = 0
        self.ORDER_STATE_CLOSED = 1
        self.ORDER_STATE_CANCELED = 2

        self.ORDER_TYPE_BUY = 0
        self.ORDER_TYPE_SELL = 1

        self.success_quantity = 0
        self.total = 0

        for exchange in exchanges:
            exchange.exchange_name = exchange.GetName()

    def getFee(self):
        """手续费"""

        return {'sell': 0.2 / 100, 'buy': 0.2 / 100}

    def getAccountInfo(self):
        """获取交易所的账号的信息"""

        total_stocks = 0
        total_balance = 0
        details = []
        for exchange in self.exchanges:
            account_info = _C(exchange.GetAccount)
            total_balance = total_balance + account_info.Balance + account_info.FrozenBalance
            total_stocks = total_stocks + account_info.Stocks + account_info.FrozenStocks
            details.append(
                {'exchange': exchange, 'exchange_name': exchange.exchange_name, 'account_info': account_info})

        data = {'total_balance': total_balance,
                'total_stocks': total_stocks,
                'details': details
                }
        return data

    def cancelPendingOrders(self):
        """取消所有未完成挂单"""

        for exchange in self.exchanges:
            orders = _C(exchange.GetOrders)

            if (len(orders) == 0):
                continue
            i = 0  # 重试次数
            for order in orders:
                while True:
                    order_status = exchange.CancelOrder(order.Id)
                    Log(order_status)
                    order_info = _C(exchange.GetOrder, order.Id)
                    if order_info['Status'] == self.ORDER_STATE_CLOSED:
                        break

                    if (order_info['Status'] == self.ORDER_STATE_CANCELED):
                        exchange_name = _C(exchange.GetName)
                        if order_info['Type'] == self.ORDER_TYPE_SELL:
                            order_type = '卖单'
                        else:
                            order_type = '买单'

                        Log('%s取消了%s,订单号:%s,下单金额%s,下单数量%s,成交量%s,' % (exchange_name, order_type, order_info[
                            'Id'], order_info['Price'], order_info['Amount'], order_info['DealAmount']), '#FF0000')
                        break

                    Sleep(self.checkTryTime)

    def getDeapList(self):
        """异步获取所有平台的深度"""

        details = []
        datas = []
        for exchange in self.exchanges:
            datas.append(
                {'exchange': exchange, 'async': exchange.Go('GetDepth')})

        for data in datas:
            deap_list, status = data['async'].wait(500)

            if status and deap_list != None:
                details.append(
                    {'exchange': data['exchange'], 'deap_list': deap_list})
                exchange_name = data['exchange'].exchange_name
                Log(exchange_name, '当前平台卖单深度', deap_list['Asks'])
                Log(exchange_name, '当前平台买单深度', deap_list['Bids'])

            else:
                exchange_name = _C(exchange.GetName)
                Log('%s获取市场深度失败' % (exchange_name))
                return False

        return details

    def calcSpreads(self, sell_info, buy_price):
        """计算差价如果差价大于设置的值就返回差价,否则返回false"""

        fee = self.getFee()
        spreads = (sell_info['price'] * (1 - fee['sell'] - self.slippage) -
                   buy_price * (1 + fee['buy'] + self.slippage)) * sell_info['amount']

        return _N(spreads, 8)

    def getBuyPrice(self, details, quantity):
        """获取数量达到我们要卖的货币数量时候的价格"""
        amount = 0
        for ask in details['deap_list']['Asks']:
            amount = amount + ask['Amount']
            if amount >= quantity:
                return _N(ask['Price'] * (1 + self.slippage), 8)

    def getSellInfo(self, details):
        i = 0
        price = details['deap_list']['Bids'][i]['Price'] * (1 - self.slippage)
        bid_amount = details['deap_list']['Bids'][i]['Amount']
        quantity_list = [bid_amount, self.maxSell]
        amount = min(quantity_list)
        sell_info = {'exchange': details['exchange'],
                     'amount': amount, 'price': _N(price, 8)}
        return sell_info

    def getTransInfo(self, details_list, account_info):
        """计算最优的组合 返回最优的一个组合,如果没有最优的,就返回空字典"""
        best_info = {}
        max_spreads = 0
        for sell_data in details_list:
            sell_info = self.getSellInfo(sell_data)
            for buy_data in details_list:
                if (not sell_data['exchange'] is buy_data['exchange']) or sell_data['exchange'].exchange_name != buy_data['exchange'].exchange_name:
                    buy_price = self.getBuyPrice(buy_data, sell_info['amount'])
                    current_spreads = self.calcSpreads(sell_info, buy_price)
                    Log(current_spreads)

                    if current_spreads > max_spreads:
                        max_spreads = current_spreads
                        best_info = {'sell_info': {'exchange': sell_info['exchange'], 'price': sell_info['price'], 'amount': sell_info['amount']},
                                     'buy_info': {'exchange': buy_data['exchange'], 'price': buy_price},
                                     'max_spreads': max_spreads}
        return best_info

    def sellCoin(self, sell_info):
        """高价卖出货币"""
        order_id = self.transaction(sell_info['exchange'], sell_info[
                                    'exchange'].Sell, sell_info['price'], sell_info['amount'])

        return order_id

    def buyCoin(self, buy_info, quantity):
        """低价买入币"""
        order_id = self.transaction(buy_info['exchange'], buy_info[
            'exchange'].Buy, buy_info['price'], quantity)
        return order_id

    def getOrderStatus(self, exchange, order_id):
        """规定时间内,查看订单状态"""

        order_info = _C(exchange.GetOrder, order_id)
        Log(order_info)
        try_quantity = 1
        while order_info['Status'] == self.ORDER_STATE_PENDING:
            Sleep(self.checkTryTime)
            try_quantity = try_quantity + 1
            order_info = _C(exchange.GetOrder, order_id)

        return True

    def transaction(self, exchange, func, price, quanyity):

        order_id = func(price, quanyity)
        if order_id == None:
            return False
        return order_id

    def run(self):
        """运行搬砖"""
        self.cancelPendingOrders()
        account_info = self.getAccountInfo()
        deap_list = self.getDeapList()
        if not deap_list:
            return False
        transInfo = self.getTransInfo(deap_list, account_info)
        # self.success(transInfo)
        if len(transInfo) == 0:
            Log('当前利差小于规定值')
            return False
        Log("当前利差为 %f" % (transInfo['max_spreads']))
        if transInfo['max_spreads'] > self.spreads:
            status = self.sellCoin(transInfo['sell_info'])
            status = self.buyCoin(transInfo['buy_info'], transInfo[
                                  'sell_info']['amount'])

    def stop(self, init_ststus):
        """检测是否停止搬砖"""
        account_info = self.getAccountInfo()
        self.printAccountInfo(account_info)
        profit = account_info['total_balance'] - init_ststus['total_balance']
        LogProfit(profit)
        if profit < self.maxLoss:
            return False
        for data in account_info['details']:
            if data['account_info']['Balance'] < self.minBlance:
                Log('基础货币小于最低值,停止搬运')
                return False
            if data['account_info']['Stocks'] < self.minSell:
                Log('要搬砖的货币小于最低值,停止搬运')
                return False
            if data['account_info']['FrozenBalance'] > 0 or data['account_info']['FrozenStocks'] > 0:
                Log('%s有货币被冻结' % (data['exchange_name']))
        self.balanceCurrency(account_info, init_ststus)

        return True

    def printAccountInfo(self, account_info):
        """打印交易所账号信息"""
        msg = '交易基础货币总数:%s,搬砖货币总数:%s,' % (
            account_info['total_balance'], account_info['total_stocks'])

        for data in account_info['details']:
            sub_msg = '%s当前数据信息:剩余基础货币%s,被冻结的基础货币%s,剩余搬砖货币:%s,被冻结的搬砖货币%s' % (data['exchange_name'], data['account_info']['Balance'], data[
                                                                             'account_info']['FrozenBalance'], data['account_info']['Stocks'], data['account_info']['FrozenStocks'])
            msg = msg + sub_msg

        Log(msg, '#4D4DFF')

    def balanceCurrency(self, new_account_info, init_account_info):
        """当要搬砖的货币比刚开始的时候少最小交易量的时候,就开始回购,相反就卖出"""
        diff = init_account_info['total_stocks'] - \
            new_account_info['total_stocks']
        if abs(diff) > self.minSell:
            deap_list = self.getDeapList()
            if not deap_list:
                return False
            transInfo = self.getTransInfo(deap_list, new_account_info)
            if len(transInfo) == 0:
                return False
            Log(transInfo)
            if diff > 0:
                Log('买入数字币以实现平仓', '#23238E')
                self.buyCoin(transInfo['buy_info'], diff)
            else:
                Log('卖出数字币以实现平仓', '#23238E')
                transInfo['sell_info']['amount'] = abs(diff)
                self.sellCoin(transInfo['sell_info'])

    def success(self, transInfo):
        """模拟请求成功,记录信息"""

        if transInfo['max_spreads'] > 0:
            date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            self.success_quantity = self.success_quantity + 1
            self.total = self.total + transInfo['max_spreads']
            Log(date, '利差', '%f' % (transInfo['max_spreads']), transInfo['sell_info']['exchange'].exchange_name, '卖出信息', transInfo['sell_info'],
                transInfo['buy_info']['exchange'].exchange_name, '买入信息', transInfo['buy_info'], '搬运成功次数', self.success_quantity, '理想状态下总利润', self.total)


def main():
    global init_ststus
    check_try_time = 100  # 重试时间间隔
    spreads = 0.000002  # 利差
    max_sell = 0.1  # 一次最多交易量
    min_sell = 0.01  # 一次最少交易量
    min_blance = 1000  # 最少交易货币
    max_loss = -0.0001    # 当亏损超过这个值的时候停止运行
    slippage = 0.001  # 滑点

    robot = Robot(exchanges, check_try_time, spreads,
                  max_sell, min_sell, min_blance, max_loss, slippage)
    init_ststus = robot.getAccountInfo()
    robot.printAccountInfo(init_ststus)
    i = 1
    while True:
        Log('第%d轮对冲开始,已经成功%d' % (i, robot.success_quantity), "#00FF00")
        robot.run()
        status = robot.stop(init_ststus)
        if status == False:
            break
        i = i + 1
        Sleep(check_try_time * 2)
