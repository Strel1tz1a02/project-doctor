package com.example.slowquery.controller;

import com.example.slowquery.dto.StatsVO;
import com.example.slowquery.service.OrderStatsService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/admin")
public class AdminStatsController {

    private final OrderStatsService orderStatsService;

    public AdminStatsController(OrderStatsService orderStatsService) {
        this.orderStatsService = orderStatsService;
    }

    @GetMapping("/stats")
    public StatsVO stats() {
        return orderStatsService.buildStats();
    }
}
