<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import type { TripPlan } from "@/types/trip";
import MapView from "./MapView.vue";
import BudgetPanel from "./BudgetPanel.vue";
import DayTimeline from "./DayTimeline.vue";

const props = defineProps<{ plan: TripPlan }>();

// 可编辑副本：用户在前端删除行程项 / 修改备注后，不影响原始 API 返回。
const editable = reactive(JSON.parse(JSON.stringify(props.plan))) as TripPlan;

watch(
  () => props.plan,
  (v) => {
    Object.assign(editable, JSON.parse(JSON.stringify(v)));
  },
  { deep: true }
);

// 汇总所有需要标注的地理点（景点 + 酒店）。
const spots = computed(() => {
  const arr: { name: string; lng: number; lat: number; kind: string }[] = [];
  editable.days.forEach((d) => {
    d.attractions.forEach((a) =>
      arr.push({
        name: a.name,
        lng: a.location.longitude,
        lat: a.location.latitude,
        kind: "景点",
      })
    );
    if (d.hotel)
      arr.push({
        name: d.hotel.name,
        lng: d.hotel.location.longitude,
        lat: d.hotel.location.latitude,
        kind: "酒店",
      });
  });
  return arr;
});

// ---- 行程编辑：由 DayTimeline 的 emit 驱动，修改 editable 副本 ----
function onRemoveAttraction(dayIdx: number, attrIdx: number) {
  editable.days[dayIdx]?.attractions.splice(attrIdx, 1);
  recomputeBudget();
}
function onRemoveMeal(dayIdx: number, mealIdx: number) {
  editable.days[dayIdx]?.meals.splice(mealIdx, 1);
  recomputeBudget();
}
function onUpdateNotes(dayIdx: number, value: string) {
  if (editable.days[dayIdx]) editable.days[dayIdx].notes = value;
}

// 删除景点/餐饮后，本地重算门票、餐饮与总计，让金额随编辑实时变化。
// 酒店（间夜）、交通（城际火车/市内打车）不因删除景点/餐饮而变，保持原值。
function recomputeBudget() {
  const b = editable.budget;
  if (!b) return;
  const travelers = b.travelers ?? 1;
  let ticket = 0;
  let meal = 0;
  for (const d of editable.days) {
    ticket += d.attractions.reduce((s, a) => s + (a.ticket_price || 0), 0);
    meal += d.meals.reduce((s, m) => s + (m.price || 0), 0);
  }
  b.ticket_total = ticket * travelers;
  b.meal_total = meal * travelers;
  b.total = b.ticket_total + b.meal_total + b.hotel_total + b.transport_total;
}
</script>

<template>
  <div class="tp-card">
    <!-- 头部摘要 -->
    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px">
      <div>
        <h2 style="margin: 0; font-size: 20px">
          🗺️ {{ editable.city }}
          <span class="tp-muted" style="font-size: 14px; font-weight: 400">
            {{ editable.start_date }} ~ {{ editable.end_date }}（{{ editable.days.length }} 天）
          </span>
        </h2>
        <div style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px">
          <span
            v-for="(w, i) in editable.weather_info"
            :key="i"
            class="tp-tag"
            style="background: #fff7e6; color: #d46b08"
          >
            {{ w.date || "Day" + (i + 1) }}：{{ w.condition }} {{ w.temperature }}℃
          </span>
        </div>
      </div>
    </div>

    <!-- 主体网格 -->
    <div class="tp-grid" style="margin-top: 16px; grid-template-columns: 300px 1fr; align-items: start">
      <!-- 左列：预算 + 车次选择（内部滚动） -->
      <div class="tp-left-col">
        <BudgetPanel :budget="editable.budget" />
        <!-- 车次选择：12306 真实候选车次 + 推荐班次 -->
        <div v-if="editable.train_info && editable.train_info.length" class="tp-rail-scroll">
          <div class="tp-section-title">🚄 车次选择（12306 实时）</div>
          <div
            v-for="rec in editable.train_info"
            :key="rec.direction"
            style="border: 1px solid #f0f0f0; border-radius: 10px; padding: 12px; margin-bottom: 12px; background: #fff"
          >
            <div style="font-weight: 600; font-size: 14px; margin-bottom: 6px">
              {{ rec.direction }}
              <span class="tp-muted" style="font-weight: 400; font-size: 12px">{{ rec.date }}</span>
            </div>
            <!-- 推荐班次 -->
            <div
              v-if="rec.recommended"
              style="border: 1px solid #faad14; border-radius: 8px; padding: 10px; background: #fffbe6; margin-bottom: 8px"
            >
              <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px">
                <div>
                  <span style="background: #faad14; color: #fff; font-size: 12px; padding: 1px 6px; border-radius: 4px; margin-right: 6px">推荐</span>
                  <b style="font-size: 15px">{{ rec.recommended.train_no }}</b>
                  <span class="tp-muted" style="font-size: 13px">
                    {{ rec.recommended.from_station }} {{ rec.recommended.depart_time }} →
                    {{ rec.recommended.to_station }} {{ rec.recommended.arrive_time }}（{{ rec.recommended.duration }}）
                  </span>
                </div>
                <div v-if="rec.price_per_person != null" style="font-size: 15px; font-weight: 700; color: #d4380d">
                  ¥{{ rec.price_per_person }}<span class="tp-muted" style="font-size: 12px; font-weight: 400">/人</span>
                </div>
              </div>
              <div class="tp-muted" style="font-size: 12px; margin-top: 6px">💡 {{ rec.reason }}</div>
            </div>
            <!-- 候选车次表格（随车次面板整体滚动，不设独立滚动条） -->
            <div>
              <table style="width: 100%; font-size: 12px; border-collapse: collapse">
                <thead>
                  <tr style="color: #999; text-align: left">
                    <th style="padding: 4px 6px">车次</th>
                    <th style="padding: 4px 6px">出发</th>
                    <th style="padding: 4px 6px">到达</th>
                    <th style="padding: 4px 6px">历时</th>
                    <th style="padding: 4px 6px">最低价</th>
                    <th style="padding: 4px 6px">席别</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="t in rec.candidates.slice(0, 20)"
                    :key="t.train_no + t.depart_time"
                    :style="t.train_no === rec.recommended?.train_no ? 'background:#fffbe6; font-weight:600' : ''"
                  >
                    <td style="padding: 4px 6px">
                      {{ t.train_no }}
                      <span class="tp-muted" style="font-size: 11px">{{ t.train_type }}</span>
                    </td>
                    <td style="padding: 4px 6px">{{ t.depart_time }}</td>
                    <td style="padding: 4px 6px">{{ t.arrive_time }}</td>
                    <td style="padding: 4px 6px" class="tp-muted">{{ t.duration }}</td>
                    <td style="padding: 4px 6px">
                      <span v-if="t.min_price != null" style="color: #d4380d">¥{{ t.min_price }}</span>
                      <span v-else class="tp-muted">—</span>
                    </td>
                    <td style="padding: 4px 6px" class="tp-muted">
                      <span
                        v-for="s in t.seats.slice(0, 4)"
                        :key="s.type"
                        style="margin-right: 6px; white-space: nowrap"
                      >
                        {{ s.type }}
                        <span v-if="s.price != null" style="color: #d4380d">{{ s.price }}</span>
                        <span v-else>{{ s.remain }}</span>
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="tp-muted" style="font-size: 11px; margin-top: 6px">
              数据来自 12306 官方接口，实时查询；余票/票价随时变化，以官方下单为准。
            </div>
          </div>
        </div>
        <!-- 无车次面板时的原因提示（未填出发城市 / 未启用 / 查询失败），避免静默"功能缺失" -->
        <div v-else-if="editable.train_note" class="tp-rail-note">
          <span class="tp-muted" style="font-size: 12px">🚄 {{ editable.train_note }}</span>
        </div>
      </div>
      <!-- 右列：地图标注（右上角，行程上方）+ 逐日行程（内部滚动） -->
      <div class="tp-right-col">
        <div class="tp-map-block">
          <div class="tp-section-title">📌 地图标注</div>
          <MapView :spots="spots" :city="editable.city" :height="220" />
        </div>
        <div class="tp-timeline-scroll">
          <div class="tp-section-title">📅 逐日行程（可编辑）</div>
          <DayTimeline
            :plan="editable"
            @remove-attraction="onRemoveAttraction"
            @remove-meal="onRemoveMeal"
            @update-notes="onUpdateNotes"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 一屏布局：左列（预算+车次）与右列（地图+行程）均限制在视口高度内，
   内部各自滚动，避免长行程/多车次导致整页无限延伸。 */
.tp-left-col,
.tp-right-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: calc(100vh - 150px);
}
/* 车次选择：占满左列剩余空间并内部滚动 */
.tp-rail-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 6px;
  scrollbar-width: thin;
  scrollbar-color: #d9d9d9 transparent;
}
.tp-rail-note {
  padding: 10px 12px;
  border: 1px dashed #d9d9d9;
  border-radius: 8px;
  background: #fafafa;
}
/* 地图固定在右列顶部（右上角，行程上方） */
.tp-map-block {
  flex-shrink: 0;
}
.tp-map-block :deep(.tp-empty-map) {
  max-height: 220px;
  overflow-y: auto;
}
/* 逐日行程：占满右列剩余空间并内部滚动 */
.tp-timeline-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 6px;
  scrollbar-width: thin;
  scrollbar-color: #d9d9d9 transparent;
}
.tp-rail-scroll::-webkit-scrollbar,
.tp-timeline-scroll::-webkit-scrollbar,
.tp-map-block :deep(.tp-empty-map)::-webkit-scrollbar {
  width: 6px;
}
.tp-rail-scroll::-webkit-scrollbar-track,
.tp-timeline-scroll::-webkit-scrollbar-track,
.tp-map-block :deep(.tp-empty-map)::-webkit-scrollbar-track {
  background: transparent;
}
.tp-rail-scroll::-webkit-scrollbar-thumb,
.tp-timeline-scroll::-webkit-scrollbar-thumb,
.tp-map-block :deep(.tp-empty-map)::-webkit-scrollbar-thumb {
  background: #d9d9d9;
  border-radius: 3px;
}
.tp-rail-scroll::-webkit-scrollbar-thumb:hover,
.tp-timeline-scroll::-webkit-scrollbar-thumb:hover,
.tp-map-block :deep(.tp-empty-map)::-webkit-scrollbar-thumb:hover {
  background: #bfbfbf;
}
</style>
