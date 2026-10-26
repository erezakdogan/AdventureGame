import { useState } from 'react';
import { Text, View, type LayoutChangeEvent } from 'react-native';
import Svg, { Defs, Line, LinearGradient, Path, Stop } from 'react-native-svg';

import { colors } from '../lib/theme';

interface Series {
  values: number[];
  color: string;
  dashed?: boolean;
  fill?: boolean;
}

/** A dependency-free line chart: one filled primary series plus optional comparisons. */
export function LineChart({
  series,
  height = 180,
  baseline,
  minLabel,
  maxLabel,
}: {
  series: Series[];
  height?: number;
  baseline?: number;
  minLabel?: (v: number) => string;
  maxLabel?: (v: number) => string;
}) {
  const [width, setWidth] = useState(0);
  const onLayout = (e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width);
  const all = series.flatMap((s) => s.values).concat(baseline != null ? [baseline] : []);
  const usable = series.some((s) => s.values.length > 1);

  if (!usable) {
    return (
      <View style={{ height, alignItems: 'center', justifyContent: 'center' }} onLayout={onLayout}>
        <Text style={{ color: colors.faint }}>Not enough data to chart yet</Text>
      </View>
    );
  }

  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || Math.abs(max) * 0.01 || 1;
  const pad = 6;
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);

  const pathFor = (values: number[]) => {
    const step = values.length > 1 ? width / (values.length - 1) : 0;
    return values.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  };

  return (
    <View onLayout={onLayout}>
      {width > 0 && (
        <Svg width={width} height={height}>
          <Defs>
            {series.map((s, i) => (
              <LinearGradient key={i} id={`fill${i}`} x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={s.color} stopOpacity={0.28} />
                <Stop offset="1" stopColor={s.color} stopOpacity={0} />
              </LinearGradient>
            ))}
          </Defs>
          {baseline != null && (
            <Line
              x1={0}
              x2={width}
              y1={y(baseline)}
              y2={y(baseline)}
              stroke={colors.faint}
              strokeDasharray="4 4"
              strokeWidth={1}
            />
          )}
          {series.map((s, i) =>
            s.values.length > 1 ? (
              <Path key={`f${i}`} d={`${pathFor(s.values)} L${width},${height} L0,${height} Z`} fill={s.fill ? `url(#fill${i})` : 'none'} />
            ) : null,
          )}
          {series.map((s, i) =>
            s.values.length > 1 ? (
              <Path
                key={`l${i}`}
                d={pathFor(s.values)}
                stroke={s.color}
                strokeWidth={2}
                fill="none"
                strokeDasharray={s.dashed ? '5 4' : undefined}
                strokeLinejoin="round"
              />
            ) : null,
          )}
        </Svg>
      )}
      {(minLabel || maxLabel) && (
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
          <Text style={{ color: colors.faint, fontSize: 11 }}>{minLabel ? `Low ${minLabel(min)}` : ''}</Text>
          <Text style={{ color: colors.faint, fontSize: 11 }}>{maxLabel ? `High ${maxLabel(max)}` : ''}</Text>
        </View>
      )}
    </View>
  );
}
