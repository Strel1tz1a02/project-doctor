package com.example.slowquery.controller;

import com.example.slowquery.dto.ThreadTimestamps;
import com.example.slowquery.service.ThreadService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/threads")
public class ThreadController {

    private final ThreadService threadService;

    public ThreadController(ThreadService threadService) {
        this.threadService = threadService;
    }

    @GetMapping("/max-timestamps")
    public ThreadTimestamps maxTimestamps() {
        return threadService.maxTimestamps();
    }
}
