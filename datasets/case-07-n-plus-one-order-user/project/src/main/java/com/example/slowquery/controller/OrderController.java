package com.example.slowquery.controller;

import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.service.OrderService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping("/recent")
    public List<OrderVO> recent(@RequestParam(defaultValue = "200") int size) {
        return orderService.recentOrdersWithUser(size);
    }
}
