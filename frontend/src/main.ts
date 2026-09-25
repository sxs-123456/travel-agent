import { createApp } from "vue";
import Button from "ant-design-vue/es/button";
import Input from "ant-design-vue/es/input";
import Progress from "ant-design-vue/es/progress";
import "ant-design-vue/dist/reset.css";
import App from "./App.vue";
import "./styles/global.css";

createApp(App)
  .use(Button)
  .use(Input)
  .use(Progress)
  .mount("#app");
