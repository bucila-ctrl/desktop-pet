# 🐶 Desktop Pet · doei

一个陪你专注与休息的桌面小狗  
*A desktop pet for focus, breaks, and gentle motivation.*

<p align="center">
  <img src="assets/dog_sit_tr.gif" width="200" alt="doei sitting">
</p>

---

## 📌 项目简介 | Introduction

**Desktop Pet · doei** 是一个基于 **Python + PySide6** 开发的桌面宠物应用。  
**Desktop Pet · doei** is a desktop pet application built with **Python and PySide6**.

它会常驻在桌面最上层，通过动画、气泡提示和交互行为，陪伴你学习、写作或工作。  
It stays on top of your screen and gently accompanies you while you study, write, or work through animations, speech bubbles, and interactions.

它不是一个“吵闹的桌宠”，而是一个 **低打扰、可关闭、可控制的陪伴工具**。  
It is not a noisy or distracting desktop toy, but a **calm, controllable, and unobtrusive companion**.

---

## ✨ 功能特性 | Features

### 🐾 基础状态 | Basic States

- 🧍 **Sit（专注）**：默认状态，安静陪伴  
  🧍 **Sit (Focus)**: Default state, quietly keeping you company

- 🛌 **Lay Down（休息）**：休息 / 番茄钟休息阶段  
  🛌 **Lay Down (Rest)**: Used during breaks or Pomodoro rest periods

- 🚶 **Walk（散步）**：沿屏幕边缘自动来回走动  
  🚶 **Walk**: Automatically walks back and forth along the screen edge

---

### 🍅 番茄钟 | Pomodoro Timer

- 默认 **25 分钟专注 + 5 分钟休息**  
  Default **25 minutes focus + 5 minutes break**

- 气泡中实时显示倒计时  
  Countdown is displayed in the speech bubble

- 可手动切换「专注 / 休息」  
  Manually switch between *Focus* and *Rest*

- 番茄钟运行期间不会触发自动散步，避免干扰  
  Auto-walk is disabled while the Pomodoro timer is running to avoid distractions

---

### 💤 休息提醒 | Rest Reminder

- 可开启 / 关闭  
  Can be enabled or disabled

- 默认每 **50 分钟**提醒一次  
  Reminds you every **50 minutes** by default

- 支持 **Snooze（延迟 10 分钟）**  
  Supports **Snooze (10-minute delay)**

- 提醒时自动切换为「躺下」动画  
  Automatically switches to the *Lay Down* animation during reminders

---

### 🚶 自动散步 | Auto Walk Roundtrip

- 每 **30 分钟**自动触发一次  
  Automatically triggered every **30 minutes**

- 小狗会：  
  The dog will:
  - 走到屏幕一侧  
    Walk to one side of the screen
  - 转身  
    Turn around
  - 再走到另一侧  
    Walk to the other side
  - 停下并恢复专注状态  
    Stop and return to focus state

- 可在托盘菜单中关闭  
  Can be disabled from the system tray menu

---

### 💬 随机鼓励 | Random Chatter

- 随机弹出轻量鼓励语  
  Randomly displays short, lightweight encouragement messages

- 适合写论文 / Coding / 学习场景  
  Designed for writing, coding, and studying scenarios

- 可随时关闭  
  Can be turned off at any time

---

### 🖱 交互操作 | Interaction

- **左键拖动**：移动桌宠（支持吸附屏幕边缘）  
  **Left-click drag**: Move the pet (supports screen-edge snapping)

- **滚轮缩放**：调整大小（0.3× – 2.0×）  
  **Mouse wheel**: Scale size (0.3× – 2.0×)

- **左键单击**：弹出鼓励语  
  **Left-click**: Show an encouragement message

- **左键双击**：切换「专注 / 休息」  
  **Double left-click**: Toggle between *Focus* and *Rest*

- **右键菜单**：打开功能菜单  
  **Right-click**: Open the context menu

- **锁定模式**：防止误拖动  
  **Lock mode**: Prevent accidental dragging

---

## 🧰 技术栈 | Tech Stack

- Python 3.9+
- PySide6 (Qt for Python)
- QMovie (GIF animations)
- QSystemTrayIcon (system tray)
- QSettings (persistent configuration)

---

## 📂 项目结构 | Project Structure

```text
desktop-pet-doei/
├─ desktop_pet_doei.py
├─ assets/
│  ├─ dog_sit_tr.gif
│  ├─ dog_laydown_tr.gif
│  ├─ dog_walkingleft_tr.gif
│  ├─ dog_walkingright_tr.gif
│  └─ tray.ico
├─ README.md
