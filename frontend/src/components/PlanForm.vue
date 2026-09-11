<script setup lang="ts">
import { reactive, computed } from "vue";
import dayjs from "dayjs";
import type { TripPlanRequest } from "@/types/trip";

const emit = defineEmits<{ (e: "submit", req: TripPlanRequest): void }>();
defineProps<{ loading?: boolean }>();

// 完全真实模式：表单不留任何预设「城市」默认值。
// 旧版默认 city="北京" 会导致用户没改城市就直接生成 → 拿到北京的景点，
// 看起来像「景点和目的地对不上」。这里改为空字符串，由下面 onSubmit 校验拦截。
// 其它项（偏好、预算档位、人数）属于选项枚举/合理分类默认值，不是数据 Mock，保留。
const form = reactive<TripPlanRequest>({
  city: "",
  start_date: dayjs().add(1, "day").format("YYYY-MM-DD"),
  end_date: dayjs().add(3, "day").format("YYYY-MM-DD"),
  preferences: "自然风光、历史文化",
  budget_level: "中等",
  travelers: 1,
  origin_city: "",
});

const trimmedCity = computed(() => (form.city || "").trim());
const canSubmit = computed(() => !!trimmedCity.value);

function onSubmit() {
  // 真实模式：城市必填；空/纯空格一律不允许提交，避免再次出现「北京景点代替 XX 城市」的错位。
  if (!canSubmit.value) {
    // eslint-disable-next-line no-alert
    alert("请先填写目的地城市（高德 POI 只能按真实城市检索，不能用默认值代填）。");
    return;
  }
  // 落库前去掉前后空格，避免「南昌 / 南昌  / 南昌市」在 POI 检索里产生歧义。
  emit("submit", { ...form, city: trimmedCity.value });
}
</script>

<template>
  <div>
    <div class="tp-section-title">🧭 行程偏好</div>
    <a-form layout="vertical" :model="form">
      <a-form-item label="目的地城市" required>
        <a-input
          v-model:value="form.city"
          placeholder="必填，如 南昌 / 上海 / 杭州（不带「市」更准）"
        />
      </a-form-item>
      <a-form-item label="出发城市（可选，用于 12306 真实票价）">
        <a-input
          v-model:value="form.origin_city"
          placeholder="如 上海；留空则交通按估算"
        />
      </a-form-item>
      <a-form-item label="出发日期">
        <a-date-picker
          v-model:value="form.start_date"
          value-format="YYYY-MM-DD"
          style="width: 100%"
        />
      </a-form-item>
      <a-form-item label="返程日期">
        <a-date-picker
          v-model:value="form.end_date"
          value-format="YYYY-MM-DD"
          style="width: 100%"
        />
      </a-form-item>
      <a-form-item label="景点偏好">
        <a-input v-model:value="form.preferences" placeholder="如 自然风光、美食" />
      </a-form-item>
      <a-form-item label="预算等级（决定酒店档次）">
        <a-select v-model:value="form.budget_level">
          <a-select-option value="经济">经济（快捷酒店）</a-select-option>
          <a-select-option value="中等">中等（三星/舒适）</a-select-option>
          <a-select-option value="豪华">豪华（五星/高档）</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item label="出行人数">
        <a-input-number v-model:value="form.travelers" :min="1" :max="20" style="width: 100%" />
      </a-form-item>
      <a-button
        type="primary"
        block
        :loading="loading"
        :disabled="!canSubmit"
        @click="onSubmit"
      >
        ✨ 生成行程
      </a-button>
    </a-form>
    <p class="tp-muted" style="margin-top: 10px">
      本项目仅真实模式（需配置 LLM / 高德 Key）。城市为空时无法提交——避免再次出现「默认
      北京景点替代真实目的地」的错位（高德 POI 必须按真实城市检索，无法由默认值代填）。
      其它项：偏好、预算档位、人数、出发日期均为合理默认，但所有景点/酒店/门票/封面图均由真实接口拉取。
    </p>
  </div>
</template>
