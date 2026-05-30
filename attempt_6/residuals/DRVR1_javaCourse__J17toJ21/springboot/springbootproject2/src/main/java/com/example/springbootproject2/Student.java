package com.example.springbootproject2;

import org.springframework.context.annotation.Scope;
import org.springframework.stereotype.Component;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@AllArgsConstructor
@NoArgsConstructor
@Component
@Scope("prototype")
public class Student {
    private int id;
    private String name;
    private int avg;
}
