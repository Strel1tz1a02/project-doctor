package com.example.slowquery.controller;

import com.example.slowquery.dto.MetricsVO;
import com.example.slowquery.service.MetricsAggregateService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.sql.SQLException;

@RestController
@RequestMapping("/api/metrics")
public class MetricsController {

    private final MetricsAggregateService metricsAggregateService;

    public MetricsController(MetricsAggregateService metricsAggregateService) {
        this.metricsAggregateService = metricsAggregateService;
    }

    @GetMapping("/aggregate")
    public MetricsVO aggregate(@RequestParam(defaultValue = "16") int models) throws SQLException {
        return metricsAggregateService.aggregate(models);
    }
}
