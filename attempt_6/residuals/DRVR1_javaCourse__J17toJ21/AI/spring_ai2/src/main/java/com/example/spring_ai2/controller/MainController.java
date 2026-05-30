package com.example.spring_ai2.controller;

import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

// http://localhost:8080/swagger-ui/index.html
@RestController
public class MainController {

    @Autowired
    private OpenAiChatModel chatModel;

    @GetMapping("/askGPT")
    public String askGPT(@RequestParam String prompt) {
        String response = chatModel.call(prompt);
        return response;
    }
}