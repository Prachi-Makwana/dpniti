# DPniti Academic Portal

A full-stack academic dashboard and student portal built for a university environment. The project combines a secure authentication system, student/faculty information dashboards, document access, timetable viewing, and an AI-powered academic chatbot to support students and staff.

## Project Overview

This system helps users:
- Sign in securely with role-based access
- View academic dashboard and profile information
- Browse faculty and student records
- Access timetable and academic documents
- Ask academic questions through an AI chatbot connected to institutional data

## Tech Stack

- Frontend: HTML, CSS, JavaScript
- Backend: Node.js, Express.js
- Database: MySQL
- Chatbot: Python, FastAPI, OpenRouter / LLM integration
- Infrastructure: Docker, Docker Compose, Nginx

## Architecture

- `frontend/` — static web interface for login, dashboard, faculty pages, profile, timetable, and documents
- `backend/` — authentication API with JWT-based login/logout and session verification
- `chatbot/` — AI assistant for academic queries with SQL-based retrieval and observability
- `database/` — database schema for login and academic data
- `docker-compose.yml` — spins up the full application stack
- `nginx.conf` — serves the frontend and routes requests

## Key Features

- Role-based login and secure session handling
- Protected academic dashboard and user access flow
- Faculty directory and student-related information views
- Timetable and document accessibility
- AI-enabled chatbot for academic assistance
- Containerized deployment for easy setup and scalability

## Getting Started

1. Clone the repository
2. Configure environment variables for the backend and chatbot as needed
3. Run:

```bash
docker compose up --build
```

4. Open the app in the browser:
- Frontend: http://localhost
- Backend API: http://localhost:5000
- Chatbot: http://localhost:5001

## Project Structure

```text
.
├── backend/
├── chatbot/
├── database/
├── frontend/
├── docker-compose.yml
├── nginx.conf
├── README.md
└── .env
```

## Role in the Project

This project demonstrates practical implementation of:
- Full-stack web development
- Authentication and authorization
- Database-driven application design
- Integration of AI into an academic workflow
- Deployment using modern container-based architecture

## Summary

DPniti is a complete academic support platform designed to improve student and faculty interaction through a modern dashboard and AI assistant. It reflects a strong combination of frontend development, backend services, database design, and intelligent system integration.
