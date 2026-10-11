package com.example.slowquery.controller;

import com.example.slowquery.dto.PageVO;
import com.example.slowquery.service.ItemService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/items")
public class ItemController {

    private final ItemService itemService;

    public ItemController(ItemService itemService) {
        this.itemService = itemService;
    }

    @GetMapping("/page")
    public PageVO page(@RequestParam(defaultValue = "0") int offset,
                       @RequestParam(defaultValue = "20") int limit) {
        return itemService.pageItems(offset, limit);
    }
}
