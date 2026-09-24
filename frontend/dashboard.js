// Dashboard JavaScript - Auto-sliding images and interactions

// Function to generate 2026 calendars
function generateCalendars() {
    const months = ['January', 'February', 'March', 'April', 'May', 'June',
                    'July', 'August', 'September', 'October', 'November', 'December'];
    const weekdays = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
    
    for (let month = 0; month < 12; month++) {
        const container = document.getElementById(`calendar-container-${month + 1}`);
        
        if (!container) continue;
        
        // Create calendar grid
        const calendarGrid = document.createElement('div');
        calendarGrid.className = 'calendar-grid';
        
        // Add month header
        const header = document.createElement('div');
        header.className = 'calendar-header';
        header.textContent = months[month].toUpperCase();
        calendarGrid.appendChild(header);
        
        // Add weekday headers
        const weekdaysDiv = document.createElement('div');
        weekdaysDiv.className = 'calendar-weekdays';
        weekdays.forEach(day => {
            const dayDiv = document.createElement('div');
            dayDiv.className = 'calendar-weekday';
            dayDiv.textContent = day;
            weekdaysDiv.appendChild(dayDiv);
        });
        calendarGrid.appendChild(weekdaysDiv);
        
        // Calculate days in month
        const daysInMonth = new Date(2026, month + 1, 0).getDate();
        const firstDay = new Date(2026, month, 1).getDay();
        
        // Create days container
        const daysDiv = document.createElement('div');
        daysDiv.className = 'calendar-days';
        
        // Add empty cells for days before month starts
        for (let i = 0; i < firstDay; i++) {
            const emptyDay = document.createElement('div');
            emptyDay.className = 'calendar-day other-month';
            daysDiv.appendChild(emptyDay);
        }
        
        // Add days of month
        for (let day = 1; day <= daysInMonth; day++) {
            const dayDiv = document.createElement('div');
            dayDiv.className = 'calendar-day';
            
            // Determine day of week
            const dayOfWeek = (firstDay + day - 1) % 7;
            
            // Highlight weekends (Sunday = 0, Saturday = 6)
            if (dayOfWeek === 0 || dayOfWeek === 6) {
                dayDiv.classList.add('weekend');
            }
            
            // Highlight today if it's in this month
            const today = new Date();
            if (today.getMonth() === month && today.getDate() === day && today.getFullYear() === 2026) {
                dayDiv.classList.add('today');
            }
            
            dayDiv.textContent = day;
            daysDiv.appendChild(dayDiv);
        }
        
        calendarGrid.appendChild(daysDiv);
        container.appendChild(calendarGrid);
    }
}

// Function to open Academic Calendar PDF
function openCalendarPDF() {
    window.location.href = 'documents/acad_cal.pdf';
}

// Function to open Division Timetable
function openDivisionTimetable() {
    // Get the current slide index from slider4
    const slider4 = document.getElementById('slider4');
    const slides = slider4.querySelectorAll('.slide');
    let currentIndex = 0;
    let currentImage = null;
    
    slides.forEach((slide, index) => {
        if (slide.classList.contains('active')) {
            currentIndex = index;
            const img = slide.querySelector('img');
            currentImage = img ? img.src : null;
        }
    });
    
    // Open the timetable image in full size
    if (currentImage) {
        window.location.href = currentImage;
    }
}

// Function to open Exam Files based on currently active slide
function openExamFileFromSlider() {
    const slider3 = document.getElementById('slider3');
    const slides = slider3.querySelectorAll('.slide');
    
    slides.forEach((slide, index) => {
        if (slide.classList.contains('active')) {
            if (index === 0) {
                // IA
                window.location.href = 'images/academic/ia.jpeg';
            } else if (index === 1) {
                // MIDS
                window.location.href = 'documents/mids2026.pdf';
            } else if (index === 2) {
                // ENDS
                window.location.href = 'images/academic/ends.jpeg';
            }
        }
    });
}

// Function to open Exam Files (IA, MIDS, ENDS)
function openExamFile(type) {
    let fileUrl;
    
    if (type === 'ia') {
        fileUrl = 'images/academic/ia.jpeg';
    } else if (type === 'mids') {
        fileUrl = 'documents/mids2026.pdf';
    } else if (type === 'ends') {
        fileUrl = 'images/academic/ends.jpeg';
    }
    
    if (fileUrl) {
        window.location.href = fileUrl;
    }
}

// Function to open Holiday PDF
function openHolidayPDF() {
    window.location.href = 'documents/holiday.pdf';
}

// Initialize all sliders
const sliders = [
    { id: 'slider1', dotsId: 'dots1', interval: 2000 },
    { id: 'slider2', dotsId: 'dots2', interval: 2000 },
    { id: 'slider3', dotsId: 'dots3', interval: 2000 },
    { id: 'slider4', dotsId: 'dots4', interval: 2000 }
];

class ImageSlider {
    constructor(sliderId, dotsId, interval = 2000) {
        this.slider = document.getElementById(sliderId);
        this.dotsContainer = document.getElementById(dotsId);
        this.slides = this.slider.querySelectorAll('.slide');
        this.currentSlide = 0;
        this.interval = interval;
        this.autoPlayTimer = null;
        
        this.init();
    }
    
    init() {
        // Create dots
        this.createDots();
        
        // Start autoplay
        this.startAutoPlay();
        
        // Pause on hover
        this.slider.addEventListener('mouseenter', () => this.stopAutoPlay());
        this.slider.addEventListener('mouseleave', () => this.startAutoPlay());
    }
    
    createDots() {
        this.slides.forEach((_, index) => {
            const dot = document.createElement('div');
            dot.classList.add('dot');
            if (index === 0) dot.classList.add('active');
            dot.addEventListener('click', () => this.goToSlide(index));
            this.dotsContainer.appendChild(dot);
        });
        this.dots = this.dotsContainer.querySelectorAll('.dot');
    }
    
    goToSlide(index) {
        // Add exiting animation to current slide
        this.slides[this.currentSlide].classList.add('exiting');
        
        // Remove active and exiting classes after animation completes
        setTimeout(() => {
            this.slides[this.currentSlide].classList.remove('active');
            this.slides[this.currentSlide].classList.remove('exiting');
            this.dots[this.currentSlide].classList.remove('active');
            
            // Add active class to new slide and dot
            this.currentSlide = index;
            this.slides[this.currentSlide].classList.add('active');
            this.dots[this.currentSlide].classList.add('active');
        }, 300);
    }
    
    nextSlide() {
        const next = (this.currentSlide + 1) % this.slides.length;
        this.goToSlide(next);
    }
    
    startAutoPlay() {
        this.autoPlayTimer = setInterval(() => this.nextSlide(), this.interval);
    }
    
    stopAutoPlay() {
        if (this.autoPlayTimer) {
            clearInterval(this.autoPlayTimer);
            this.autoPlayTimer = null;
        }
    }
}

// Initialize all sliders when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Generate 2026 calendars
    generateCalendars();
    
    // Initialize sliders
    sliders.forEach(slider => {
        new ImageSlider(slider.id, slider.dotsId, slider.interval);
    });
    
    // Navbar scroll effect
    const navbar = document.getElementById('navbar');
    let lastScroll = 0;
    
    window.addEventListener('scroll', () => {
        const currentScroll = window.pageYOffset;
        
        if (currentScroll > 100) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
        
        lastScroll = currentScroll;
    });
    
    // Mobile menu toggle
    const hamburger = document.getElementById('hamburger');
    const navMenu = document.getElementById('navMenu');
    
    hamburger.addEventListener('click', () => {
        navMenu.classList.toggle('active');
        
        // Animate hamburger
        const spans = hamburger.querySelectorAll('span');
        if (navMenu.classList.contains('active')) {
            spans[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
            spans[1].style.opacity = '0';
            spans[2].style.transform = 'rotate(-45deg) translate(7px, -6px)';
        } else {
            spans[0].style.transform = 'none';
            spans[1].style.opacity = '1';
            spans[2].style.transform = 'none';
        }
    });
    
    // Close menu when clicking on a link
    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            navMenu.classList.remove('active');
            const spans = hamburger.querySelectorAll('span');
            spans[0].style.transform = 'none';
            spans[1].style.opacity = '1';
            spans[2].style.transform = 'none';
        });
    });
    
    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                const offsetTop = target.offsetTop - 80; // Account for navbar height
                window.scrollTo({
                    top: offsetTop,
                    behavior: 'smooth'
                });
            }
        });
    });
    
    // Add scroll animations
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -100px 0px'
    };
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.animation = 'fadeInUp 0.6s ease forwards';
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);
    
    // Observe tab cards and action cards
    document.querySelectorAll('.tab-card, .action-card').forEach(card => {
        card.style.opacity = '0';
        observer.observe(card);
    });
    
    // Check if user is logged in
    const authToken = localStorage.getItem('authToken');
    if (!authToken) {
        // Redirect to login if not authenticated
        // Uncomment the line below to enable authentication check
        // window.location.href = 'index.html';
    }
    
    // Profile button now opens the dedicated profile page.
    const profileBtn = document.querySelector('.profile-btn');
    if (profileBtn) {
        profileBtn.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.href = 'profile.html';
        });
    }
});

// Add CSS animation for cards
const style = document.createElement('style');
style.textContent = `
    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
`;
document.head.appendChild(style);
