package com.example.slowquery.controller;

import com.example.slowquery.dto.CounterResultVO;
import com.example.slowquery.service.CounterService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/counters")
public class CounterController {

    private final CounterService counterService;

    public CounterController(CounterService counterService) {
        this.counterService = counterService;
    }

    @GetMapping("/increment")
    public CounterResultVO increment(@RequestParam(defaultValue = "CNT-1") String key) {
        return counterService.incrementHot(key);
    }
}
