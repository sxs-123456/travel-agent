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
  // 交通拆成城际与市内两行；地图路线不可用时不展示虚构的打车金额。
  if (b.rail_total) {
    list.push({
      label: b.rail_is_estimated ? "城际·火车（估算）" : "城际·火车（12306）",
      value: b.rail_total,
      color: "#722ed1",
    });
  }
  if (b.taxi_total) {
    list.push({
      label: "市内打车（路线参考价）",
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
    <p v-if="budget.taxi_total && !budget.taxi_is_estimated" class="tp-muted" style="font-size: 11px; margin: -2px 0 0">
      这是全程路线参考价：按酒店与每天首个景点往返路线估算，实际车费以打车平台为准。
    </p>
    <p v-else-if="budget.taxi_is_estimated" class="tp-muted" style="font-size: 11px; margin: -2px 0 0">
      暂未取得可用的地图路线，市内打车费用未计入总预算；路线可用后会显示参考价。
    </p>
  </div>
</template>
