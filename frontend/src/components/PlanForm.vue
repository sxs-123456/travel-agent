<script setup lang="ts">
import { computed, ref, watch } from "vue";

const props = defineProps<{ loading?: boolean; initialQuery?: string; error?: string }>();
const emit = defineEmits<{ (e: "submit", query: string): void; (e: "edit"): void }>();
const query = ref(props.initialQuery ?? "");
const canSubmit = computed(() => query.value.trim().length >= 5 && !props.loading);

watch(() => props.initialQuery, (value) => { query.value = value ?? ""; });
watch(query, () => emit("edit"));

function submit() {
  if (canSubmit.value) emit("submit", query.value.trim());
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <form class="prompt-form" @submit.prevent="submit">
    <label class="sr-only" for="travel-request">描述你的旅行计划</label>
    <textarea
      id="travel-request"
      v-model="query"
      class="prompt-input"
      rows="4"
      maxlength="1000"
      :disabled="loading"
      placeholder="例如：十月一日到七日从上海去北京旅行，想逛故宫和胡同，喜欢美食，预算中等，两人同行……"
      @keydown="onKeydown"
    />
    <div class="prompt-bottom">
      <p class="prompt-hint">写下目的地和出行日期，也可以补充人数、预算与喜好。<span>回车生成 · Shift + 回车换行</span></p>
      <button class="prompt-submit" type="submit" :disabled="!canSubmit">
        <span v-if="loading" class="prompt-spinner" aria-hidden="true"></span>
        {{ loading ? "正在规划…" : "生成我的行程" }}
        <span v-if="!loading" aria-hidden="true">↗</span>
      </button>
    </div>
    <p v-if="error" class="prompt-error" role="alert">{{ error }}</p>
  </form>
</template>
