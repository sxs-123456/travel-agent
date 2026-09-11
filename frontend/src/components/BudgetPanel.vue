<script setup lang="ts">
import { computed } from "vue";
import type { Budget } from "@/types/trip";

const props = defineProps<{ budget: Budget | null | undefined }>();

const rows = computed(() => {
  const b = props.budget;
  if (!b) return [];
  const list = [
    { label: "门票", value: b.ticket_total, color: "#2f6bff" },
    { label: b.rooms && b.rooms > 1 ? `酒店（${b.rooms} 间）` : "酒店", value: b.hotel_total, color: "#52c41a" },
    { label: "餐饮", value: b.meal_total, color: "#fa8c16" },
  ];
  // 交通拆「城际(火车) + 市内(打车/短驳)」两行，明确标注「市内/城际」避免与火车混淆；
  // 各自标注真实/估算来源（百度实时 = 真实，档位×天 = 估算）。
  if (b.rail_total) {
    list.push({
      label: b.rail_is_estimated ? "城际·火车（估算）" : "城际·火车（12306）",
      value: b.rail_total,
      color: "#722ed1",
    });
  }
  if (b.taxi_total) {
    list.push({
      label: b.taxi_is_estimated ? "市内·打车（估算）" : "市内·打车（百度）",
      value: b.taxi_total,
      color: "#13c2c2",
    });
  }
  const total = b.total || list.reduce((s, x) => s + x.value, 0);
  return list.map((x) => ({
    ...x,
    pct: total ? Math.round((x.value / total) * 100) : 0,
  }));
});
</script>

<template>
  <div v-if="budget">
    <div class="tp-section-title">💰 预算明细</div>
    <div style="font-size: 28px; font-weight: 700; color: #d4380d; margin-bottom: 14px">
      ¥{{ budget.total }}
      <span class="tp-muted" style="font-size: 13px">总计</span>
    </div>
    <div v-for="r in rows" :key="r.label" style="margin-bottom: 12px">
      <div style="display: flex; justify-content: space-between; font-size: 13px">
        <span>{{ r.label }}</span>
        <span class="tp-muted">¥{{ r.value }} · {{ r.pct }}%</span>
      </div>
      <a-progress
        :percent="r.pct"
        :stroke-color="r.color"
        :show-info="false"
        size="small"
      />
    </div>
  </div>
</template>
