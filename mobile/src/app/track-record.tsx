import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { AccuracyCard, PredictionRow } from '../components/Forecasts';
import { Body, Button, Card, Empty, ErrorBanner, Label, Notice, Screen, Segmented } from '../components/ui';
import { api } from '../lib/api';
import { colors, space } from '../lib/theme';
import { useApi } from '../lib/useApi';

type Source = 'all' | 'analyses' | 'funds';
type Status = 'all' | 'open' | 'scored';

export default function TrackRecord() {
  const params = useLocalSearchParams<{ fund_id?: string; title?: string }>();
  const fundId = params.fund_id ? Number(params.fund_id) : undefined;
  const [source, setSource] = useState<Source>('all');
  const [status, setStatus] = useState<Status>('all');
  const [checking, setChecking] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const src = fundId ? undefined : source === 'all' ? undefined : source;
  const stats = useApi(() => api.predictionStats({ source: src, fund_id: fundId }), [src, fundId], 60000);
  const list = useApi(
    () => api.predictions({ source: src, fund_id: fundId, status: status === 'all' ? undefined : status }),
    [src, fundId, status],
    30000,
  );

  const check = async () => {
    setChecking(true);
    setNote(null);
    try {
      const r = await api.evaluatePredictions();
      setNote(r.scored ? `Scored ${r.scored} forecast${r.scored === 1 ? '' : 's'} that came due.` : 'Nothing new to score yet.');
      stats.refresh();
      list.refresh();
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setChecking(false);
    }
  };

  return (
    <Screen
      refreshing={list.refreshing}
      onRefresh={() => {
        stats.reload();
        list.reload();
      }}
    >
      {params.title ? <Label>{params.title}</Label> : null}
      {!fundId && (
        <Segmented
          value={source}
          onChange={setSource}
          options={[
            { label: 'Everything', value: 'all' },
            { label: 'Analyses', value: 'analyses' },
            { label: 'AI funds', value: 'funds' },
          ]}
        />
      )}
      <ErrorBanner message={stats.error} />
      <AccuracyCard stats={stats.data} />
      <Button title="Score due forecasts now" kind="secondary" onPress={check} loading={checking} />
      {note ? <Notice color={colors.info}>{note}</Notice> : null}

      <Card>
        <Label style={{ marginBottom: space.sm }}>Forecasts</Label>
        <Segmented
          style={{ marginBottom: space.sm }}
          value={status}
          onChange={setStatus}
          options={[
            { label: 'All', value: 'all' },
            { label: 'Open', value: 'open' },
            { label: 'Scored', value: 'scored' },
          ]}
        />
        <ErrorBanner message={list.error} />
        {list.data?.predictions.length === 0 && (
          <Empty title="No forecasts yet">
            Every finished analysis and every AI fund trade records one, with its target price and deadline.
          </Empty>
        )}
        {(list.data?.predictions ?? []).map((p) => (
          <PredictionRow key={p.id} p={p} />
        ))}
      </Card>
      <Body muted style={{ fontSize: 12, textAlign: 'center' }}>
        The server scores forecasts about every five minutes once their deadline has passed, using Yahoo Finance
        prices (5-minute bars for short horizons, daily bars for long ones).
      </Body>
    </Screen>
  );
}
