import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { LineChart } from '../../components/LineChart';
import { RunRow } from '../../components/RunRow';
import {
  Body,
  Button,
  Card,
  ErrorBanner,
  Field,
  KV,
  Label,
  Loading,
  Notice,
  Row,
  Screen,
  Segmented,
} from '../../components/ui';
import { api } from '../../lib/api';
import { money, pct, price, qty, signedMoney } from '../../lib/format';
import { colors, pnlColor, space } from '../../lib/theme';
import { useApi } from '../../lib/useApi';

const PERIODS = {
  '1D': ['1d', '5m'],
  '1W': ['5d', '30m'],
  '1M': ['1mo', '1d'],
  '6M': ['6mo', '1d'],
  '1Y': ['1y', '1d'],
  '5Y': ['5y', '1wk'],
} as const;
type Period = keyof typeof PERIODS;

export default function SymbolScreen() {
  const { symbol: raw } = useLocalSearchParams<{ symbol: string }>();
  const symbol = decodeURIComponent(String(raw)).toUpperCase();
  const [period, setPeriod] = useState<Period>('6M');

  const quote = useApi(() => api.quote(symbol), [symbol], 15000);
  const hist = useApi(() => api.history(symbol, PERIODS[period][0], PERIODS[period][1]), [symbol, period]);
  const acct = useApi(() => api.account(), [symbol], 30000);
  const runs = useApi(() => api.runs(symbol), [symbol], 10000);
  const watch = useApi(() => api.watchlist(), [symbol]);

  const q = quote.data;
  const pos = acct.data?.positions.find((p) => p.symbol === symbol);
  const closes = (hist.data?.bars ?? []).map((b) => b.c);
  const first = closes[0];
  const last = closes[closes.length - 1];
  const watched = watch.data?.symbols.includes(symbol);

  return (
    <Screen
      refreshing={quote.refreshing}
      onRefresh={() => {
        quote.reload();
        hist.reload();
        acct.reload();
      }}
    >
      <Stack.Screen options={{ title: symbol }} />
      <ErrorBanner message={quote.error} />
      {!q && quote.loading ? (
        <Loading />
      ) : q ? (
        <Card>
          <Body muted numberOfLines={1}>
            {q.name ?? symbol} {q.currency ? `· ${q.currency}` : ''}
          </Body>
          <Text style={{ color: colors.text, fontSize: 32, fontWeight: '800', marginTop: 2 }}>{price(q.price)}</Text>
          <Text style={{ color: pnlColor(q.change), fontWeight: '600' }}>
            {signedMoney(q.change)} ({pct(q.change_pct)}) today
          </Text>
          <View style={{ marginTop: space.lg }}>
            <LineChart
              series={[{ values: closes, color: last >= first ? colors.up : colors.down, fill: true }]}
              height={170}
              minLabel={price}
              maxLabel={price}
            />
          </View>
          <Segmented
            style={{ marginTop: space.md }}
            value={period}
            onChange={setPeriod}
            options={(Object.keys(PERIODS) as Period[]).map((p) => ({ label: p, value: p }))}
          />
          {first && last ? (
            <Body muted style={{ fontSize: 12, marginTop: 6 }}>
              {period} change {pct(((last - first) / first) * 100)}
            </Body>
          ) : null}
        </Card>
      ) : null}

      <Row style={{ gap: space.sm }}>
        <Button
          title="🤖 Run AI analysis"
          style={{ flex: 1 }}
          onPress={() => router.push({ pathname: '/agents', params: { ticker: symbol } })}
        />
        <Button
          title={watched ? '★ Watching' : '☆ Watch'}
          kind="secondary"
          onPress={async () => {
            await (watched ? api.unwatch(symbol) : api.watch(symbol)).catch(() => undefined);
            watch.refresh();
          }}
        />
      </Row>

      {pos && (
        <Card>
          <Label style={{ marginBottom: space.sm }}>Your position</Label>
          <KV k="Quantity" v={qty(pos.quantity)} />
          <KV k="Average cost" v={price(pos.avg_price)} />
          <KV k="Market value" v={money(pos.market_value)} />
          <KV
            k="Unrealized P&L"
            v={`${signedMoney(pos.unrealized_pnl)} (${pct(pos.unrealized_pnl_pct)})`}
            color={pnlColor(pos.unrealized_pnl)}
          />
          <KV k="Portfolio weight" v={`${pos.weight_pct.toFixed(1)}%`} />
        </Card>
      )}

      {q && (
        <OrderTicket
          symbol={symbol}
          lastPrice={q.price}
          held={pos?.quantity ?? 0}
          cash={acct.data?.cash ?? 0}
          onDone={() => {
            acct.refresh();
            quote.refresh();
          }}
        />
      )}

      {(runs.data?.runs.length ?? 0) > 0 && (
        <Card>
          <Label style={{ marginBottom: space.sm }}>AI analyses of {symbol}</Label>
          {runs.data!.runs.map((r) => (
            <RunRow key={r.id} run={r} />
          ))}
        </Card>
      )}
    </Screen>
  );
}

function OrderTicket({
  symbol,
  lastPrice,
  held,
  cash,
  onDone,
}: {
  symbol: string;
  lastPrice: number;
  held: number;
  cash: number;
  onDone: () => void;
}) {
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [type, setType] = useState<'market' | 'limit' | 'stop'>('market');
  const [unit, setUnit] = useState<'shares' | 'dollars'>('shares');
  const [amount, setAmount] = useState('');
  const [trigger, setTrigger] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const n = Number(amount);
  const ref = type === 'market' ? lastPrice : Number(trigger) || lastPrice;
  const estimate = unit === 'shares' ? n * ref : n;

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (!(n > 0)) throw new Error('Enter an amount');
      const t = Number(trigger);
      if (type !== 'market' && !(t > 0)) throw new Error(`Enter a ${type} price`);
      const o = await api.placeOrder({
        symbol,
        side,
        order_type: type,
        ...(unit === 'shares' ? { quantity: n } : { notional: n }),
        ...(type === 'limit' ? { limit_price: t } : {}),
        ...(type === 'stop' ? { stop_price: t } : {}),
      });
      setResult(
        o.status === 'filled'
          ? `Filled: ${o.side} ${qty(o.quantity)} at ${price(o.fill_price)}`
          : o.status === 'open'
            ? `Order placed and waiting (#${o.id})`
            : `Order ${o.status}: ${o.reject_reason ?? ''}`,
      );
      setAmount('');
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <Label style={{ marginBottom: space.md }}>Trade manually</Label>
      <Segmented
        value={side}
        onChange={setSide}
        options={[
          { label: 'Buy', value: 'buy' },
          { label: 'Sell', value: 'sell' },
        ]}
      />
      <Segmented
        style={{ marginTop: space.sm }}
        value={type}
        onChange={setType}
        options={[
          { label: 'Market', value: 'market' },
          { label: 'Limit', value: 'limit' },
          { label: 'Stop', value: 'stop' },
        ]}
      />
      <Segmented
        style={{ marginTop: space.sm, marginBottom: space.md }}
        value={unit}
        onChange={setUnit}
        options={[
          { label: 'Shares / units', value: 'shares' },
          { label: 'Dollars', value: 'dollars' },
        ]}
      />
      <Field
        label={unit === 'shares' ? 'Quantity' : 'Amount in USD'}
        value={amount}
        onChangeText={setAmount}
        keyboardType="decimal-pad"
        placeholder={unit === 'shares' ? '10' : '1000'}
        hint={side === 'sell' ? `You hold ${qty(held)}.` : `Cash available ${money(cash)}.`}
      />
      {type !== 'market' && (
        <Field
          label={type === 'limit' ? 'Limit price' : 'Stop price'}
          value={trigger}
          onChangeText={setTrigger}
          keyboardType="decimal-pad"
          placeholder={price(lastPrice)}
          hint={
            type === 'limit'
              ? side === 'buy'
                ? 'Buys when the price falls to this level or lower.'
                : 'Sells when the price rises to this level or higher.'
              : side === 'sell'
                ? 'Sells if the price drops to this level (stop-loss).'
                : 'Buys if the price rises to this level (breakout).'
          }
        />
      )}
      {n > 0 && (
        <Body muted style={{ fontSize: 13, marginBottom: space.sm }}>
          Estimated {money(estimate)}
          {unit === 'dollars' ? ` ≈ ${qty(Math.floor((n / ref) * 1e4) / 1e4)} units` : ''}
        </Body>
      )}
      <ErrorBanner message={error} />
      {result ? <Notice color={colors.up}>{result}</Notice> : null}
      <Button
        title={`${side === 'buy' ? 'Buy' : 'Sell'} ${symbol}`}
        kind={side === 'buy' ? 'buy' : 'sell'}
        onPress={submit}
        loading={busy}
        style={{ marginTop: space.sm }}
      />
    </Card>
  );
}
