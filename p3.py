init_account_info = {}


class Robot():
    def __init__(self, exchanges, check_try_time, spreads, max_sell, min_sell, max_loss, slippage):
        self.exchanges = exchanges
        self.checkTryTime = check_try_time
        self.spreads = spreads
        self.maxSell = max_sell
        self.minSell = min_sell
        self.maxLoss = max_loss
        self.slippage = slippage

        self.ORDER_STATE_PENDING = 0
        self.ORDER_STATE_CLOSED = 1
        self.ORDER_STATE_CANCELED = 2

        self.ORDER_TYPE_BUY = 0
        self.ORDER_TYPE_SELL = 1

        self.success_quantity = 0
        self.total = 0

        self.pair_1 = 'BAT_USDT'  # 交易对1
        self.pair_2 = 'BAT_ETH'  # 交易对2

        self.middleman = 'ETH_USDT'  # 中间人 交易对通过中间人转换为相同的价格单位,对比价格 p1/中间人 和p2对比

        for exchange in self.exchanges:
            exchange.exchange_name = exchange.GetName()
            exchange.CURRENCY = exchange.GetCurrency()
            exchange.QUOTE = exchange.GetQuoteCurrency()

    def getAccountInfo(self):
        """获取交易所的账号的信息"""

        details = []
        for exchange in self.exchanges:
            account_info = _C(exchange.GetAccount)
            total_stocks = account_info.Stocks + account_info.FrozenStocks
            details.append(
                {'currency': exchange.CURRENCY,
                 'account_info': {'total_stocks': total_stocks, 'stocks': account_info.Stocks,
                                  'frozenStocks': account_info.FrozenStocks}})

        return details

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

        currency_list = {}
        datas = []
        for exchange in self.exchanges:
            datas.append(
                {'exchange': exchange, 'async': exchange.Go('GetDepth')})

        for data in datas:
            deap_list, status = data['async'].wait(500)

            if status and deap_list != None:
                asks_info = deap_list['Asks']
                bids_info = deap_list['Bids']
                name = str(data['exchange'].CURRENCY, encoding="UTF-8")

                data['exchange'].deapList = deap_list
                data['exchange'].asksInfo = asks_info
                data['exchange'].bidsInfo = bids_info

                data['exchange'].sellPrice = self.getSellPrice(bids_info)
                data['exchange'].sellMaxQuantity = self.getMaxSellQuantity(bids_info)

                data['exchange'].buyPrice = self.getBuyPrice(asks_info)
                data['exchange'].buyMaxQuantity = self.getMaxBuyQuantity(asks_info)

                currency_list.update({name: data['exchange']})

                # Log(data['exchange'].CURRENCY, '当前平台卖单深度', deap_list['Asks'])
                # Log(data['exchange'].CURRENCY, '当前平台买单深度', deap_list['Bids'])

            else:
                exchange_name = _C(exchange.GetName)
                Log('%s获取市场深度失败' % (exchange_name))
                return False

        return currency_list

    def getBuyPrice(self, asks):
        """从卖单数组 (按价格从低向高排序) 返回一个购买价格"""

        price = asks[self.slippage]['Price']
        return price

    def getBuyPriceInclueFee(self, price):
        """返回加上手续费买价"""
        return price * (1 + 0.002)

    def getSellPriceInclueFee(self, price):
        """返回加上手续费卖价"""
        return price * (1 - 0.002)

    def getMaxBuyQuantity(self, asks):
        """从卖单数组里面 返回我们当前这个价格下可以购买币的最大数量"""

        return asks[self.slippage]['Amount']

    def getSellPrice(self, bids):
        """从买单数组(按价格从高向低排序) 返回一个出售价格"""

        price = bids[self.slippage]['Price']
        return price

    def getMaxSellQuantity(self, bids):
        """从买单数组里面返回我们当前这个价格下可以购买币的最大数量"""
        return bids[self.slippage]['Amount']

    def sellCoin(self, sell_info):
        """高价卖出货币"""
        order_id = self.transaction(sell_info['exchange'], sell_info['exchange'].Sell, sell_info['price'],
                                    sell_info['amount'])
        return order_id

    def buyCoin(self, buy_info, quantity):
        """低价买入币"""
        order_id = self.transaction(buy_info['exchange'], buy_info['exchange'].Buy, buy_info['price'], quantity)
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
        """发起交易"""
        order_id = func(price, quanyity)
        if order_id == None:
            return False
        return order_id

    def moreFair(self, currency_list, quantity=100):
        """p1卖q个币-> ->p2买q个币 通过中间人转换(买操作) 赚中间人的定价币 默认返回卖一个币的利润"""

        pair_1_price = self.getSellPriceInclueFee(currency_list[self.pair_1].sellPrice)
        middleman_price = self.getBuyPriceInclueFee(currency_list[self.middleman].buyPrice)
        pair_2_price = self.getBuyPriceInclueFee(currency_list[self.pair_2].buyPrice)
        spread_quantity = quantity * pair_1_price - pair_2_price * quantity * middleman_price
        Log('p1卖价格%s,p2买入的价格%s,中间人的价格%s ,p2转换单位后价格%s 根据公式得到结果%s' % (
            pair_1_price, pair_2_price, middleman_price, middleman_price * pair_2_price, spread_quantity))
        return spread_quantity

    def lessFair(self, currency_list, quantity=100):
        """p1买q个币-> ->p2买卖q个币 通过中间人转换(卖操作) 赚中间人的定价币 默认返回卖一个币的利润 """

        pair_1_price = self.getBuyPriceInclueFee(currency_list[self.pair_1].buyPrice)
        middleman_price = self.getSellPriceInclueFee(currency_list[self.middleman].sellPrice)
        pair_2_price = self.getSellPriceInclueFee(currency_list[self.pair_2].sellPrice)
        spread_quantity = quantity * pair_2_price * middleman_price - quantity * pair_1_price

        Log('p1买价格%s,p2卖出入的价格%s,中间人的价格%s ,p2转换单位后价格%s 根据公式得到结果%s' % (
            pair_1_price, pair_2_price, middleman_price, pair_2_price * middleman_price, spread_quantity))

        return spread_quantity

    def getLessFailQuantity(self, currency_list):
        """当是less fail 时候计算要交易的pair的个数 和 中间人的个数"""

        pair_1_price = self.getBuyPriceInclueFee(currency_list[self.pair_1].buyPrice)
        middleman_price = self.getSellPriceInclueFee(currency_list[self.middleman].sellPrice)
        tmp = currency_list[self.middleman].sellMaxQuantity * middleman_price / pair_1_price
        quantity_list = [currency_list[self.pair_1].buyMaxQuantity, currency_list[self.pair_2].sellMaxQuantity, tmp]
        quantity = min(quantity_list)

        pair_2_price = self.getBuyPriceInclueFee(currency_list[self.pair_2].buyPrice)
        middleman_quantity = quantity * pair_2_price
        return (quantity, middleman_quantity)

    def getMoreFailQuantity(self, currency_list):
        """当是more fail 时候计算要交易的pair的个数 和 中间人的个数"""

        pair_1_price = self.getSellPriceInclueFee(currency_list[self.pair_1].sellPrice)
        middleman_price = self.getBuyPriceInclueFee(currency_list[self.middleman].buyPrice)
        tmp = currency_list[self.middleman].buyMaxQuantity * middleman_price / pair_1_price
        quantity_list = [currency_list[self.pair_1].sellMaxQuantity, currency_list[self.pair_2].buyMaxQuantity, tmp]
        quantity = min(quantity_list)

        middleman_quantity = quantity * pair_1_price / middleman_price
        return (quantity, middleman_quantity)

    def run(self):
        """运行搬砖"""

        currency_list = self.getDeapList()
        if not currency_list:
            return False

            #  Log(self.moreFair(currency_list))
            #  Log(self.lessFair(currency_list))

        if self.lessFair(currency_list) > 0:
            Log(self.lessFair(currency_list))

            quantity, middleman_quantity = self.getLessFailQuantity(currency_list)
            currency_list[self.pair_1].Buy(currency_list[self.pair_1].buyPrice, quantity)
            currency_list[self.pair_2].Sell(currency_list[self.pair_2].sellPrice, quantity)
            currency_list[self.middleman].Sell(currency_list[self.pair_2].sellPrice, middleman_quantity)

        if self.moreFair(currency_list) > 0:
            Log(self.moreFair(currency_list))

            quantity, middleman_quantity = self.getMoreFailQuantity(currency_list)
            currency_list[self.pair_2].Buy(currency_list[self.pair_2].buyPrice, quantity)
            currency_list[self.pair_1].Sell(currency_list[self.pair_1].sellPrice, quantity)
            currency_list[self.middleman].Buy(currency_list[self.pair_2].buyPrice, middleman_quantity)

    def stop(self, init_ststus):
        """检测是否停止搬砖"""
        account_info = self.getAccountInfo()
        self.printAccountInfo(account_info)
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
        msg = ''
        for data in account_info:
            sub_msg = '%s数量:一共有:%s,可使用:%s,被冻结:%s,' % (
                data['currency'], data['account_info']['total_stocks'], data['account_info']['stocks'],
                data['account_info']['frozenStocks'])
            msg = msg + sub_msg

        Log(msg, '#4D4DFF')


def main():
    global init_ststus
    check_try_time = 100  # 重试时间间隔
    spreads = 0.000002  # 利差
    max_sell = 10  # 一次最多交易量
    min_sell = 1  # 一次最少交易量
    max_loss = -0.0001  # 当亏损超过这个值的时候停止运行
    slippage = 0  # 滑点 深度的级别0 为最大

    robot = Robot(exchanges, check_try_time, spreads, max_sell, min_sell, max_loss, slippage)
    init_account_info = robot.getAccountInfo()
    robot.printAccountInfo(init_account_info)
    i = 1

    while i < 100000:
        Log('第%d轮对冲开始' % (i), "#00FF00")
        robot.run()
        i = i + 1
        Sleep(check_try_time)
