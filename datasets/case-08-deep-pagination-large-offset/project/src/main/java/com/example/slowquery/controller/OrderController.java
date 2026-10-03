package com.example.slowquery.controller;

import com.example.slowquery.dto.PageVO;
import com.example.slowquery.service.OrderService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping("/page")
    public PageVO page(@RequestParam(defaultValue = "1") int page,
                       @RequestParam(defaultValue = "20") int size) {
        return orderService.pageOrders(page, size);
    }
}
