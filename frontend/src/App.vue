<script setup lang="ts">
import { ref } from "vue";
import { message } from "ant-design-vue";
import type { TripPlan, TripPlanRequest } from "@/types/trip";
import { createTripPlan } from "@/api/client";
import PlanForm from "@/components/PlanForm.vue";
import TripResult from "@/components/TripResult.vue";

const loading = ref(false);
const plan = ref<TripPlan | null>(null);

async function onPlan(req: TripPlanRequest) {
  loading.value = true;
  try {
    plan.value = await createTripPlan(req);
    message.success("行程生成完成");
  } catch (e: any) {
    console.error("[trip-plan error]", e);
    message.error(formatError(e, "生成失败，请检查日期是否合法 / 网络是否正常"));
  } finally {
    loading.value = false;
  }
}

function formatError(e: any, fallback: string): string {
  const m = e?.message;
  if (typeof m === "string" && m && !m.includes("[object")) return m;
  return fallback;
}
</script>

<template>
  <div class="tp-container">
    <header class="tp-header">
      <div class="tp-logo">旅</div>
      <div>
        <h1 class="tp-title">智能旅行助手</h1>
        <p class="tp-subtitle">多智能体行程规划 · Vue3 + FastAPI + 高德地图</p>
      </div>
    </header>

    <div class="tp-grid">
      <div class="tp-card">
        <PlanForm :loading="loading" @submit="onPlan" />
      </div>
      <div>
        <TripResult v-if="plan" :plan="plan" />
        <div v-else class="tp-card tp-empty-map">
          <p>填写左侧偏好，点击「✨ 生成行程」开始规划 👈</p>
        </div>
      </div>
    </div>

  </div>
</template>
